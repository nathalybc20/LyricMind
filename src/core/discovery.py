import logging
from typing import Optional, Dict, Any, List
from src.providers.genius import GeniusProvider
from src.providers.lyrics_ovh import LyricsOVHProvider
from src.providers.musixmatch import MusixmatchProvider # Ensure this is imported
from src.core.config import Config
from src.core.database import Database

logger = logging.getLogger(__name__)

class LyricsDiscovery:
    def __init__(self, config: Config, database: Database):
        self.config = config
        self.db = database
        self.providers = self._create_providers()
    
    def _create_providers(self) -> List[Any]: # Changed to List[Any] for provider instances
        """Create available providers based on configuration, ordered by preference"""
        providers = []
        
        # Highest preference (paid, potentially better quality)
        if self.config.musixmatch_api_key:
            providers.append(MusixmatchProvider(self.config.musixmatch_api_key))
            logger.info("Musixmatch provider initialized.")
        
        if self.config.genius_token:
            providers.append(GeniusProvider(self.config.genius_token))
            logger.info("Genius provider initialized.")
        
        # Free provider (lowest priority)
        providers.append(LyricsOVHProvider())
        logger.info("LyricsOVH provider initialized.")
        
        if not providers:
            logger.warning("No lyrics providers are configured or initialized!")
            
        return providers
    
    def search_lyrics(self, artist: str, title: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Search for lyrics with caching. Providers are tried in order of preference."""
        # Check cache first
        if not force_refresh:
            cached_result = self.db.get_cached_lyrics(artist, title)
            if cached_result:
                logger.info(f"Found cached lyrics for '{artist} - {title}' from source: {cached_result.get('source')}")
                return cached_result
        
        # Search providers in the order they were added
        for provider in self.providers:
            provider_name = provider.__class__.__name__
            try:
                logger.info(f"Searching with provider: {provider_name} for '{artist} - {title}'")
                result = provider.search(artist, title)
                
                if result and result.get('lyrics') and self._is_valid_lyrics(result['lyrics']):
                    # Store in cache
                    lyrics_text = result.pop('lyrics') # Use .pop to get and remove for storage
                    source = result.pop('source')
                    # Any other metadata from result can be passed via **result
                    self.db.store_lyrics(artist, title, lyrics_text, source, **result)
                    
                    # Return complete result including the popped items
                    logger.info(f"Found lyrics for '{artist} - {title}' from {source} via {provider_name}.")
                    return {
                        'artist': artist,
                        'title': title,
                        'lyrics': lyrics_text,
                        'source': source,
                        **result # Add back any other metadata
                    }
                elif result:
                    logger.info(f"Lyrics found by {provider_name} for '{artist} - {title}' but deemed invalid or empty.")
                    
            except Exception as e:
                logger.warning(f"Provider {provider_name} failed for '{artist} - {title}': {e}", exc_info=True)
                continue # Try next provider
        
        logger.warning(f"No valid lyrics found for '{artist} - {title}' after trying all providers.")
        return None
    
    def _is_valid_lyrics(self, lyrics: str) -> bool:
        """Simple lyrics validation to avoid storing junk or placeholder text."""
        if not lyrics or not isinstance(lyrics, str):
            return False
        
        stripped_lyrics = lyrics.strip()
        if len(stripped_lyrics) < 50: # Arbitrary minimum length
            logger.debug(f"Lyrics too short: {len(stripped_lyrics)} chars.")
            return False
        
        # Check for common quality issues / placeholder texts
        lyrics_lower = stripped_lyrics.lower()
        quality_issues = [
            "lyrics not available",
            "instrumental",
            "no lyrics found",
            "sorry, we don't have",
            "we are not authorized",
            "lyrics are currently unavailable",
            "*******", # Musixmatch disclaimer start
            "not for commercial use"
        ]
        
        for phrase in quality_issues:
            if phrase in lyrics_lower:
                logger.debug(f"Lyrics contain quality issue phrase: '{phrase}'")
                return False
        
        # Check for excessive repetition (e.g., placeholder error messages repeated)
        lines = stripped_lyrics.split('\n')
        if len(lines) > 5 and len(set(lines)) < len(lines) / 2: # If more than half lines are duplicates
            logger.debug("Lyrics contain excessive line repetition.")
            return False
            
        return True
