import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(__filename, '../../..');
const frontendDir = path.join(projectRoot, 'frontend');

function collectFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const result = [];

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      result.push(...collectFiles(fullPath));
      continue;
    }

    if (entry.name.endsWith('.html') || entry.name.endsWith('.js')) {
      result.push(fullPath);
    }
  }

  return result;
}

function isExternalTarget(target) {
  return /^(?:[a-z]+:)?\/\//i.test(target)
    || /^[a-z]+:/i.test(target)
    || target.startsWith('#')
    || target.startsWith('javascript:')
    || target.startsWith('mailto:')
    || target.startsWith('tel:');
}

function resolveTarget(target) {
  const cleaned = target.trim();
  if (!cleaned || isExternalTarget(cleaned)) {
    return null;
  }

  const filePart = cleaned.split(/[?#]/)[0].replace(/\$\{[^}]+\}/g, '').replace(/^\.\//, '').replace(/^\//, '').replace(/\/$/, '');
  if (!filePart || filePart === '.' || filePart === '/') {
    return null;
  }

  const candidate = path.join(frontendDir, filePart);
  return fs.existsSync(candidate) && fs.statSync(candidate).isFile() ? candidate : null;
}

function collectHtmlTargets(source) {
  const matches = [...source.matchAll(/href\s*=\s*["']([^"']+)["']/gi)];
  const scriptMatches = [...source.matchAll(/src\s*=\s*["']([^"']+)["']/gi)];
  return [...matches.map((match) => match[1]), ...scriptMatches.map((match) => match[1])];
}

function collectJsTargets(source) {
  const patterns = [
    /window\.location\s*\.assign\s*\(\s*["'`]+([^"'`]+)["'`]+\s*\)/g,
    /location\.href\s*=\s*["'`]+([^"'`]+)["'`]+/g,
    /window\.location\s*=\s*["'`]+([^"'`]+)["'`]+/g,
    /location\.assign\s*\(\s*["'`]+([^"'`]+)["'`]+\s*\)/g,
  ];

  const targets = [];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      targets.push(match[1]);
    }
  }

  return targets;
}

test('every HTML link and JS redirect resolves to an existing file in frontend', () => {
  const files = collectFiles(frontendDir);
  const failures = [];

  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8');
    const targets = file.endsWith('.html') ? collectHtmlTargets(source) : collectJsTargets(source);

    for (const target of targets) {
      const resolved = resolveTarget(target);
      if (!resolved) {
        failures.push(`${path.relative(projectRoot, file)} -> ${target}`);
      }
    }
  }

  assert.deepEqual(failures, [], `Broken internal targets:\n${failures.join('\n')}`);
});
