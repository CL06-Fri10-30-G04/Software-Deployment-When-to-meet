async function checkStatus() {
  const status = document.getElementById("status");

  try {
    const response = await fetch("/api/health");

    if (!response.ok) {
      throw new Error("Health check failed");
    }

    const data = await response.json();
    status.textContent = `API status: ${data.status}`;
  } catch {
    status.textContent = "Unable to connect to the API.";
  }
}

checkStatus();