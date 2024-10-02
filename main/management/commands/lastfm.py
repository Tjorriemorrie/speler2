import time
import webbrowser

import pylast
from django.conf import settings
from django.core.management.base import BaseCommand

from main.lastfm_service import get_network


class Command(BaseCommand):
    help = 'Fetch Last.fm session key and store it in a file'

    def add_arguments(self, parser):
        """Add subparsers."""
        subparsers = parser.add_subparsers(dest='command')

        # Subparser for authentication
        subparsers.add_parser('auth', help='Authenticate with Last.fm and save session key')

        # Subparser for unfavoriting
        subparsers.add_parser('unfavorite', help='Unfavorite all loved tracks on Last.fm')

    def handle(self, *args, **kwargs):
        """Handle different subcommands."""
        if kwargs['command'] == 'auth':
            self.authenticate()
        elif kwargs['command'] == 'unfavorite':
            self.unfavorite_tracks()

    def authenticate(self):
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

    def unfavorite_tracks(self):
        """Unfavorite all loved tracks on Last.fm."""
        # Initialize the LastFMNetwork object with the session key
        network = get_network()

        try:
            self.stdout.write('Getting authenticated user...')
            authed_user = network.get_authenticated_user()
            self.stdout.write(f'User: {authed_user}')

            self.stdout.write('Getting loved tracks...')
            loved_tracks = authed_user.get_loved_tracks(limit=10)
            self.stdout.write(f'Found {len(loved_tracks)} loved tracks')

            for track in loved_tracks:
                try:
                    self.stdout.write(f'Unfavoriting track: {track.title} by {track.artist.name}')
                    track.unlove()  # Unfavorite the track
                    time.sleep(0.1)  # Add a delay between requests
                except pylast.WSError as e:
                    self.stdout.write(f'Failed to unfavorite {track.title}: {e}')

            self.stdout.write('All favorite tracks have been unfavorited.')
        except pylast.WSError as e:
            self.stdout.write(f'An error occurred while fetching loved tracks: {e}')
