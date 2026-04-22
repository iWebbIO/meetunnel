let isActive = false;

const toggleBtn = document.getElementById('toggleBtn');
const statusLabel = document.getElementById('statusLabel');
const logOutput = document.getElementById('logOutput');

toggleBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('http://127.0.0.1:5001', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: isActive ? 'stop' : 'start' })
        });

        const data = await response.json();
        isActive = data.running;
        updateUI();
        addLog(isActive ? 'Capture started' : 'Capture stopped');
    } catch (e) {
        addLog('Error: Python server unreachable on port 5001');
    }
});

function updateUI() {
    if (isActive) {
        toggleBtn.textContent = 'Stop Capture';
        statusLabel.textContent = 'Capturing';
        statusLabel.className = 'status-active';
    } else {
        toggleBtn.textContent = 'Start Capture';
        statusLabel.textContent = 'Disconnected';
        statusLabel.className = 'status-idle';
    }
}

function addLog(msg) {
    const time = new Date().toLocaleTimeString();
    logOutput.innerHTML += `\n[${time}] ${msg}`;
    logOutput.parentElement.scrollTop = logOutput.parentElement.scrollHeight;
}

// Poll status every 2 seconds
setInterval(async () => {
    try {
        const response = await fetch('http://127.0.0.1:5001');
        const data = await response.json();
        isActive = data.running;
        updateUI();
    } catch (e) {
        // Server unreachable
    }
}, 2000);

updateUI();
