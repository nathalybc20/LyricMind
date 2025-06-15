import requests
from typing import Optional, Dict, Any
from urllib.parse import quote
import logging

logger = logging.getLogger(__name__)

class LyricsOVHProvider:
    BASE_URL = "https://api.lyrics.ovh/v1"
    
    def search(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Search lyrics using lyrics.ovh API"""
        try:
            encoded_artist = quote(artist)
            encoded_title = quote(title)
            
            url = f"{self.BASE_URL}/{encoded_artist}/{encoded_title}"
            response = requests.get(url, timeout=10) # 10 seconds timeout
            
            response.raise_for_status() # Will raise HTTPError for bad responses (4xx or 5xx)
            
            data = response.json()
            lyrics = data.get('lyrics', '').strip()
            
            if lyrics:
                # Basic cleaning: replace multiple newlines with single, remove leading/trailing on each line
                cleaned_lyrics = '\n'.join([line.strip() for line in lyrics.split('\n')])
                cleaned_lyrics = requests.utils.unquote(cleaned_lyrics) # Handle URL encoded chars if any
                return {
                    'lyrics': cleaned_lyrics.strip(),
                    'source': 'lyrics_ovh',
                    'confidence': 0.7 # Confidence is lower as it's a free API with less metadata
                }
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 404:
                logger.info(f"Lyrics.ovh: No lyrics found for '{artist} - {title}' (404).")
            else:
                logger.warning(f"Lyrics.ovh API HTTP error for '{artist} - {title}': {http_err}")
        except requests.exceptions.RequestException as e:
            # Includes timeouts, connection errors, etc.
            logger.error(f"Lyrics.ovh API request error for '{artist} - {title}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error in Lyrics.ovh provider for '{artist} - {title}': {e}")
            # Do not re-raise here to allow fallback
        
        return None
