let wakeLock = null;

async function requestWakeLock() {
    try {
        // Check if Wake Lock API is supported
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen');
            alert('Screen wake lock is active');

            // Handle visibility change to automatically release the lock when the page is hidden
            document.addEventListener('visibilitychange', async () => {
                if (wakeLock !== null && document.visibilityState === 'visible') {
                    wakeLock = await navigator.wakeLock.request('screen');
                }
            });
        } else {
            alert("Wake Lock API is not supported by this browser.");
        }
    } catch (err) {
        alert(`Wake Lock request failed: ${err.message}`);
    }
}

// Call the function to request the wake lock
requestWakeLock();
