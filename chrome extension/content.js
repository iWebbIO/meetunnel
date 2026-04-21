let isCapturing = false;
let captureInterval = null;

const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');

async function syncWithScript() {
    try {
        const response = await fetch('http://127.0.0.1:5001', { mode: 'cors' });
        const data = await response.json();
        
        if (data.running && !isCapturing) {
            isCapturing = true;
            startLoop();
        } else if (!data.running && isCapturing) {
            isCapturing = false;
            stopLoop();
        }
    } catch (e) {
        if (isCapturing) {
            isCapturing = false;
            stopLoop();
        }
    }
}

// Automatically poll the Python server every 2 seconds to sync capture state
setInterval(syncWithScript, 2000);

function startLoop() {
    if (captureInterval) return;
    captureInterval = setInterval(captureFrame, 66);
    console.log("MeeTunnel: Capture Started");
}

function stopLoop() {
    clearInterval(captureInterval);
    captureInterval = null;
    console.log("MeeTunnel: Capture Stopped");
}

async function captureFrame() {
    if (!isCapturing) return;

    // Find the largest video element (likely the main speaker or presentation)
    const videos = Array.from(document.querySelectorAll('video'));
    let video = null;
    let maxArea = 0;

    videos.forEach(v => {
        const area = v.offsetWidth * v.offsetHeight;
        if (area > maxArea) {
            maxArea = area;
            video = v;
        }
    });

    if (video && video.readyState === 4) {
        // Maintain aspect ratio while drawing to 640x480
        canvas.width = 640;
        canvas.height = 480;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
        
        try {
            await fetch('http://127.0.0.1:5001', {
                method: 'POST',
                mode: 'cors',
                body: dataUrl,
                headers: { 'Content-Type': 'text/plain' }
            });
            chrome.runtime.sendMessage({type: "stats", status: "Active", lastPulse: Date.now()});
        } catch (e) {
            chrome.runtime.sendMessage({type: "stats", status: "Python Unreachable"});
        }
    }
}