import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MusixmatchProvider:
    BASE_URL = "https://api.musixmatch.com/ws/1.1"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def search(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        """Search lyrics using Musixmatch API"""
        if not self.api_key:
            logger.warning("Musixmatch API key not provided. Cannot search.")
            return None
        try:
            params = {
                'format': 'json',
                'apikey': self.api_key,
                'q_artist': artist,
                'q_track': title,
                's_track_rating': 'desc' # Get best match
            }
            
            # First, search for the track to get its ID
            track_search_url = f"{self.BASE_URL}/track.search"
            track_response = requests.get(track_search_url, params=params, timeout=10)
            track_response.raise_for_status()
            track_data = track_response.json()

            track_message = track_data.get('message', {})
            if track_message.get('header', {}).get('status_code') != 200 or not track_message.get('body', {}).get('track_list'):
                logger.info(f"Musixmatch: Track not found for '{artist} - {title}'. Response: {track_data}")
                return None

            # Get the first track (best match)
            track_info = track_message['body']['track_list'][0]['track']
            track_id = track_info.get('track_id')
            common_track_id = track_info.get('commontrack_id') # Prefer commontrack_id if available

            if not track_id and not common_track_id:
                logger.info(f"Musixmatch: No track ID found for '{artist} - {title}'.")
                return None

            # Now get lyrics using the track_id or commontrack_id
            lyrics_params = {
                'format': 'json',
                'apikey': self.api_key,
            }
            if common_track_id:
                 lyrics_params['commontrack_id'] = common_track_id
            else:
                 lyrics_params['track_id'] = track_id

            lyrics_get_url = f"{self.BASE_URL}/track.lyrics.get"
            lyrics_response = requests.get(lyrics_get_url, params=lyrics_params, timeout=10)
            lyrics_response.raise_for_status()
            lyrics_data = lyrics_response.json()
            
            lyrics_message = lyrics_data.get('message', {})
            if lyrics_message.get('header', {}).get('status_code') == 200:
                lyrics_body = lyrics_message.get('body', {}).get('lyrics', {})
                lyrics_text = lyrics_body.get('lyrics_body', '').strip()
                
                # Musixmatch often returns '******* This Lyrics is NOT for Commercial use *******' or similar
                # We should try to remove this if present and if it's a significant portion of the text it might mean no actual lyrics
                if "*******" in lyrics_text and len(lyrics_text) < 200: # Arbitrary length check
                    logger.info(f"Musixmatch: Lyrics for '{artist} - {title}' seem to be restricted or placeholder.")
                    return None

                # Remove common disclaimers
                lyrics_text = lyrics_text.split("*******")[0].strip()
                
                if lyrics_text and len(lyrics_text) > 20: # Basic check for non-empty lyrics
                    return {
                        'lyrics': lyrics_text,
                        'source': 'musixmatch',
                        'confidence': 0.8,
                        'musixmatch_id': track_id,
                        'copyright_info': lyrics_body.get('lyrics_copyright'),
                        'track_url': track_info.get('track_share_url')
                    }
                else:
                    logger.info(f"Musixmatch: Empty or very short lyrics returned for '{artist} - {title}'.")
            else:
                logger.warning(f"Musixmatch API error getting lyrics for '{artist} - {title}'. Status: {lyrics_message.get('header', {}).get('status_code')}. Response: {lyrics_data}")

        except requests.exceptions.HTTPError as http_err:
            logger.warning(f"Musixmatch API HTTP error for '{artist} - {title}': {http_err}. Response: {http_err.response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Musixmatch API request error for '{artist} - {title}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error in Musixmatch provider for '{artist} - {title}': {e}")
        
        return None
