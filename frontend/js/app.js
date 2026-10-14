const statusElement = document.getElementById("status");
const meetingList = document.getElementById("meetings-list");
const form = document.getElementById("meeting-form");
const formMessage = document.getElementById("form-message");

async function checkStatus() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();

    if (!response.ok) {
      throw new Error("Health check failed");
    }

    statusElement.textContent = data.database === "connected"
      ? "API status: connected to database"
      : `API status: ${data.status}`;
  } catch {
    statusElement.textContent = "Unable to connect to the API.";
  }
}

async function loadMeetings() {
  meetingList.replaceChildren();

  try {
    const response = await fetch("/api/meetings");

    if (!response.ok) {
      throw new Error("Could not load meetings");
    }

    const meetings = await response.json();

    if (meetings.length === 0) {
      const empty = document.createElement("li");
      empty.textContent = "No meeting meetings yet. Create one above.";
      meetingList.append(empty);
      return;
    }

    for (const meeting of meetings) {
      const item = document.createElement("li");

      const title = document.createElement("strong");
      title.textContent = meeting.title;
      item.append(title);

      if (meeting.description) {
        const description = document.createElement("p");
        description.textContent = meeting.description;
        item.append(description);
      }

      meetingList.append(item);
    }
  } catch {
    const error = document.createElement("li");
    error.textContent = "Unable to load meetings.";
    meetingList.append(error);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "";

  const formData = new FormData(form);

  try {
    const response = await fetch("/api/meetings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        title: formData.get("title"),
        description: formData.get("description")
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not create meeting");
    }

    form.reset();
    formMessage.textContent = "Meeting created.";

    await loadMeetings();
  } catch (error) {
    formMessage.textContent =
      error.message || "Unable to create meeting.";
  }
});

checkStatus();
loadMeetings();