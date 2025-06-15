import lyricsgenius
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class GeniusProvider:
    def __init__(self, token: str):
        try:
            self.genius = lyricsgenius.Genius(token, verbose=False, remove_section_headers=True, skip_non_songs=True, retries=2)
        except Exception as e:
            logger.error(f"Failed to initialize Genius client: {e}")
            self.genius = None # Ensure genius attribute exists even on failure
            # Optionally, re-raise or handle more gracefully depending on desired behavior
            # raise ConnectionError(f"Could not initialize Genius client: {e}") from e
    
    def search(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Search lyrics using Genius API"""
        if not self.genius:
            logger.warning("Genius client not initialized. Cannot search.")
            return None
        try:
            song = self.genius.search_song(title, artist)
            if song and song.lyrics:
                # Clean up lyrics: remove [Verse], [Chorus] etc. and extra newlines
                cleaned_lyrics = song.lyrics
                # The library's remove_section_headers should handle this, but as a fallback:
                import re
                cleaned_lyrics = re.sub(r'^\[.*\]\n?', '', cleaned_lyrics, flags=re.MULTILINE)
                cleaned_lyrics = '\n'.join([line for line in cleaned_lyrics.split('\n') if line.strip()])
                
                return {
                    'lyrics': cleaned_lyrics.strip(),
                    'source': 'genius',
                    'confidence': 0.9,
                    'genius_id': getattr(song, 'id', None),
                    'track_url': getattr(song, 'url', None)
                }
        except Exception as e:
            # lyricsgenius can raise various exceptions, including timeout
            logger.error(f"Genius API error for '{artist} - {title}': {e}")
            # Do not re-raise here to allow fallback to other providers
        
        return None
