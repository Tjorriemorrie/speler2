$(document).ready(function () {
    // Initialize the player once
    const $audioElement = $('audio.plyr');
    const player = new Plyr($audioElement[0], {autoplay: false});

    // Function to load the next song
    function loadNextSong() {
        console.log("loading next song...");
        htmx.ajax('GET', '/next-song/', {
            target: '#player-container',
            swap: 'innerHTML'
        });
    }

    // Listen for when the song ends
    player.on('ended', function () {
        console.log("song ended");
        loadNextSong();  // Load next song when the current one ends
    });

    // Listen for HTMX swap events
    $(document).on('htmx:afterSwap', function (event) {
        // Only scroll to top when pagination links are clicked (or similar elements)
        if ($(event.detail.target).is('#main-container')) {
            window.scrollTo({top: 0, behavior: 'smooth'});
        }

        // Check if the swap happened in the #player-container
        if ($(event.target).is('#player-container')) {
            console.log("player-container htmx swapped");

            // Update the song source dynamically
            let songSrc = $('#songData').data('songsrc');
            player.source = {
                type: 'audio',
                sources: [
                    {
                        src: songSrc,
                        type: 'audio/mp3'  // Adjust this if your audio is in a different format
                    }
                ]
            };
            console.log("Song source set to", songSrc);

            // Set the volume based on song rating
            // Scale rating from [0, 1] to [0.3, 0.7]
            let rating = $('#songData').data('rating');
            const newMax = 0.3;
            const newMin = 0.05;
            let volume = (((rating - 0) * (newMax - newMin)) / (1 - 0)) + newMin
            player.volume = volume;
            console.log("Volume set to", volume, "from rating", rating);

            // Play the audio
            player.play().catch(function (error) {
                alert('Enable autoplay in the URL bar.');
            });

            // Set the page title to the song's name
            let songTitle = $('#songData').data('songtitle');
            document.title = songTitle;
            console.log("Set title to", songTitle);

            // Load the album view on new song
            console.log("fetching album page...");
            htmx.ajax('GET', '/album/0/', {
                target: '#main-container',
                swap: 'innerHTML'
            });
        }
    });

    $(document).on('keydown', function (event) {
        // Add event listener for spacebar to pause/resume playback
        if (event.code === 'Space' && player) {
            event.preventDefault();  // Prevent the page from scrolling down
            if (player.playing) {
                player.pause();
            } else {
                player.play();
            }
        }
        // Add event listener for the "n" key to load the next song
        if (event.key === 'n' || event.code === 'KeyN') {
            console.log("pressed n");
            event.preventDefault();  // Prevent any default behavior
            loadNextSong();  // Load next song when "n" key is pressed
        }
    });
});
