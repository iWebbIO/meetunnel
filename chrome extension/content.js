console.log("QR Tunnel Capture Extension Active");

const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');

async function captureFrame() {
    // Find the video element (Meet uses video tags for feeds)
    const video = document.querySelector('video');
    if (video && video.readyState === 4) {
        canvas.width = 640;
        canvas.height = 480;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
        
        try {
            await fetch('http://127.0.0.1:5001', {
                method: 'POST',
                mode: 'no-cors',
                body: dataUrl
            });
        } catch (e) {
            console.error("Python Receiver not reachable");
        }
    }
    setTimeout(captureFrame, 66); // ~15 FPS
}

captureFrame();