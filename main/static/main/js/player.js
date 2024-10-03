$(document).ready(function () {
    // htmx.logger = function (elt, event, data) {
    //     if (console) {
    //         console.log(event, elt, data);
    //     }
    // }

    // Timezone settings
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    document.cookie = "django_timezone=" + timezone + "; path=/; SameSite=Lax";
    console.log('Timezone set ', timezone)

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
            const newMax = 0.5;
            const newMin = 0.1;
            let volume = (((rating - 0) * (newMax - newMin)) / (1 - 0)) + newMin
            player.volume = volume;
            console.log("Volume set to", volume, "from rating", rating);

            // Play the audio
            player.play().catch(function (error) {
                console.log('Enable autoplay in the URL bar.');
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


    // Add event listener for when the dropdown is hidden
    document.getElementById('checkboxDropdown').addEventListener('hidden.bs.dropdown', function () {
        console.log('Dropdown has been hidden');
        // Gather selected options
        const selectedOptions = Array.from(document.querySelectorAll('#filterChoices input[type="checkbox"]:checked'))
            .map(input => input.value)
            .join(',');

        const queryString = new URLSearchParams({filters: selectedOptions}).toString();
        htmx.ajax('GET', `/next-song/?${queryString}`, {
            target: '#player-container',
            swap: 'innerHTML'
        });
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

        const keyMap = {
            '1': '#rating-box-1',
            '2': '#rating-box-2',
            '3': '#rating-box-3'
        };
        if (keyMap[event.key]) {
            const element = document.querySelector(keyMap[event.key]);
            if (element) {
                element.click();  // Simulate a click to trigger HTMX request
            }
        }
    });
});
