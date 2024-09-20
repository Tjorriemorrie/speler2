import time
import webbrowser

import pylast
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Fetch Last.fm session key and store it in a file'

    def handle(self, *args, **kwargs):
        """Auth with LastFM."""
        # Initialize the LastFMNetwork object
        network = pylast.LastFMNetwork(
            api_key=settings.LASTFM_API_KEY, api_secret=settings.LASTFM_SECRET
        )

        if not settings.LASTFM_SESSION_FILE.exists():
            # Generate the authorization URL
            skg = pylast.SessionKeyGenerator(network)
            url = skg.get_web_auth_url()
            self.stdout.write(f'Please authorize this script to access your account: {url}\n')

            # Open the URL in the web browser
            webbrowser.open(url)

            # Wait for the user to authorize the app and get the session key
            while True:
                try:
                    session_key = skg.get_web_auth_session_key(url)
                    settings.LASTFM_SESSION_FILE.write_text(session_key)
                    self.stdout.write(f'Session key saved to {settings.LASTFM_SESSION_FILE}\n')
                    break
                except pylast.WSError:
                    time.sleep(1)
        else:
            # Read the session key from the file
            session_key = settings.LASTFM_SESSION_FILE.read_text()
            self.stdout.write(f'Session key loaded from {settings.LASTFM_SESSION_FILE}\n')

        # Set the session key for the network
        network.session_key = session_key
        self.stdout.write('Session key has been set.\n')
