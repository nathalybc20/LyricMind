from flask import Flask, request, jsonify, render_template, send_from_directory
import logging
import os
import re
from typing import Optional
from flasgger import Swagger, swag_from # Added for Swagger API docs
import threading

# Adjust import paths based on the assumption that 'api' is a package
# and the script might be run from the project root or within the 'api' directory.
# This setup assumes that the 'src' directory is in PYTHONPATH or the app is run from project root.
try:
    from src.core.config import Config
    from src.core.database import Database
    from src.core.discovery import LyricsDiscovery
    from src.core.analyzer import LyricsAnalyzer
except ImportError:
    # Fallback for running directly from api directory, assuming src is one level up and then into src
    import sys
    # Get the parent directory of the current file's directory (api/.. -> project_root)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    # Add project_root to sys.path to allow imports like from src.core...
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from src.core.config import Config
    from src.core.database import Database
    from src.core.discovery import LyricsDiscovery
    from src.core.analyzer import LyricsAnalyzer

logger = logging.getLogger(__name__)

# Global instances, initialized in create_app
# These are placeholders; they will be properly initialized within create_app context
# This avoids top-level calls to Config.load() or Database() which might not find files
# if the working directory isn't the project root at import time.
db_instance: Optional[Database] = None
discovery_service_instance: Optional[LyricsDiscovery] = None
analyzer_service_instance: Optional[LyricsAnalyzer] = None
app_config_instance: Optional[Config] = None

def create_app(config_path: Optional[str] = None) -> Flask:
    """Create Flask application with all routes"""
    app = Flask(__name__)

    # Determine project_root_dir early as it's used in multiple places
    # Assuming this (routes.py) is in api/, so project_root is one level up.
    project_root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # Swagger/Flasgger configuration
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "LyricMind API",
            "description": "API for discovering and analyzing song lyrics. Provides endpoints to search for lyrics and perform textual analysis on them.",
            "version": "1.0.0",
            "contact": {
                "name": "LyricMind Support",
                "url": "https://github.com/your-repo/LyricMind", 
                "email": "lyricmind.support@example.com"
            },
            "license": {
                "name": "MIT",
                "url": "https://opensource.org/licenses/MIT"
            }
        },
        "host": "localhost:5001", # Default host and port
        "basePath": "/api",
        "schemes": ["http", "https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "securityDefinitions": {},
        "tags": [
            {"name": "Discovery", "description": "Endpoints for discovering song lyrics"},
            {"name": "Analyzer", "description": "Endpoints for analyzing lyrics"}
        ]
    }
    # Make swagger_template accessible within Flasgger config if needed for dynamic parts
    app.config['SWAGGER_TEMPLATE'] = swagger_template

    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec_1',
                "route": '/apispec_1.json',
                "rule_filter": lambda rule: True,  # all in
                "model_filter": lambda tag: True,  # all in
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs/",
    }
    swagger = Swagger(app, config=swagger_config, template=swagger_template) # Pass template directly

    global db_instance, discovery_service_instance, analyzer_service_instance, app_config_instance

    # Determine config path
    # If config_path is not provided, use default path relative to project_root_dir
    if config_path is None:
        config_path = os.path.join(project_root_dir, "config.yaml") # project_root_dir is now defined above
    
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found at {config_path}. Cannot start API.")
        # This is a critical error, so we might raise an exception or exit
        # For now, we'll let it proceed, but Config.load will use defaults and log a warning.
        # raise FileNotFoundError(f"Configuration file not found: {config_path}")

    # Load configuration
    app_config_instance = Config.load(config_path)
    app.config['LYRICS_CONFIG'] = app_config_instance # Store for access if needed

    # Setup logging based on config
    log_level_str = app_config_instance.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    if app_config_instance.log_file:
        # Ensure log directory exists if log_file is specified
        log_file_path = os.path.join(project_root_dir, app_config_instance.log_file)
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(file_handler) # Add to root logger

    logger.info(f"Flask App: Initializing with config from {config_path}")
    logger.info(f"Flask App: Database URL is {app_config_instance.database_url}")

    # Initialize services
    db_instance = Database(app_config_instance.database_url)
    discovery_service_instance = LyricsDiscovery(app_config_instance, db_instance)
    analyzer_service_instance = LyricsAnalyzer(app_config_instance, db_instance)

    # For tracking active analyses
    active_analyses = set()
    analysis_lock = threading.Lock() # To ensure thread-safe access to active_analyses

    # Define the base directory for framework files
    FRAMEWORK_FILES_DIR = os.path.join(project_root_dir, "frameworks")  # Changed from "framework_files"
    if not os.path.isdir(FRAMEWORK_FILES_DIR):
        logger.warning(f"Framework files directory 'frameworks' does not exist or is not a directory: {FRAMEWORK_FILES_DIR}. "
                       f"The /api/analyzer/frameworks/ endpoint may not serve files.")
    
    @app.route('/api/analyzer/frameworks', methods=['GET'])
    @swag_from({
        'tags': ['Analyzer'],
        'summary': 'List all available analysis frameworks.',
        'description': 'Retrieves a list of all loaded analysis frameworks, including their names and version numbers.',
        'responses': {
            200: {
                'description': 'A list of available frameworks.',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'example': 'success'},
                        'data': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'name': {'type': 'string', 'example': 'vanilla'},
                                    'version': {'type': 'string', 'example': '1.0'}
                                }
                            }
                        }
                    }
                }
            },
            500: {'description': 'Internal server error or frameworks directory not found.'}
        }
    })
    def list_frameworks_route():
        frameworks_list = []
        # FRAMEWORK_FILES_DIR and logger are accessible from create_app scope
        if not FRAMEWORK_FILES_DIR or not os.path.isdir(FRAMEWORK_FILES_DIR):
            logger.error(f"Frameworks directory not found or not configured: {FRAMEWORK_FILES_DIR}")
            return jsonify({'status': 'error', 'message': 'Frameworks directory not configured or not found.'}), 500

        try:
            for filename in os.listdir(FRAMEWORK_FILES_DIR):
                if filename.endswith(".txt"):
                    framework_name = filename[:-4] # Remove .txt
                    version = "unknown"
                    file_path = os.path.join(FRAMEWORK_FILES_DIR, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            if len(lines) >= 2:
                                version_line = lines[1].strip()
                                # Attempt to parse version, e.g., "**Version: 1.0**" or "# Version: 1.0" or "Version: 1.0"
                                match = re.search(r"version:\s*([0-9.]+)", version_line, re.IGNORECASE)
                                if match:
                                    version = match.group(1)
                                else:
                                    logger.warning(f"Could not parse version from second line of {filename}: '{version_line}'")
                            else:
                                logger.warning(f"File {filename} has less than 2 lines, cannot extract version.")
                    except Exception as e:
                        logger.error(f"Error reading or parsing version for {filename}: {e}")
                    
                    frameworks_list.append({'name': framework_name, 'version': version})
            
            if not frameworks_list and os.path.isdir(FRAMEWORK_FILES_DIR) and not os.listdir(FRAMEWORK_FILES_DIR):
                 logger.info(f"No framework files found in {FRAMEWORK_FILES_DIR}")
            elif not frameworks_list and os.path.isdir(FRAMEWORK_FILES_DIR) and os.listdir(FRAMEWORK_FILES_DIR):
                 logger.warning(f"Framework files might be present in {FRAMEWORK_FILES_DIR}, but list is empty post-processing (e.g. all non-.txt or version parse failed)." )

            return jsonify({'status': 'success', 'data': frameworks_list}), 200
        except Exception as e:
            logger.error(f"Error listing frameworks: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to list frameworks.'}), 500


    @app.route('/')
    def home():
        """Serves the homepage."""
        # Note: Flasgger's basePath is '/api', so this route is truly at the root,
        # not /api/. If you want it under /api, define it as @app.route('/api/').
        return render_template('index.html')

    # Discovery routes
    @app.route('/api/discovery/search', methods=['POST'])
    @swag_from({
        'tags': ['Discovery'],
        'summary': 'Search for lyrics by artist and title.',
        'description': 'Searches for song lyrics using configured providers. Can optionally force a refresh from providers even if found in cache.',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'id': 'SearchLyricsRequest',
                    'type': 'object',
                    'required': ['artist', 'title'],
                    'properties': {
                        'artist': {'type': 'string', 'description': 'The name of the artist.', 'example': 'Queen'},
                        'title': {'type': 'string', 'description': 'The title of the song.', 'example': 'Bohemian Rhapsody'},
                        'force_refresh': {'type': 'boolean', 'description': 'Whether to force a refresh from providers.', 'default': False, 'example': False}
                    }
                }
            }
        ],
        'responses': {
            200: {
                'description': 'Lyrics found successfully.',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'example': 'success'},
                        'data': {
                            'type': 'object',
                            'properties': {
                                'lyrics': {'type': 'string', 'example': 'Is this the real life? Is this just fantasy?...'},
                                'source': {'type': 'string', 'example': 'lyrics_ovh'},
                                'artist': {'type': 'string', 'example': 'Queen'},
                                'title': {'type': 'string', 'example': 'Bohemian Rhapsody'}
                            }
                        }
                    }
                }
            },
            400: {'description': 'Invalid input (e.g., missing artist/title, or not JSON).'},
            404: {'description': 'Lyrics not found.'},
            500: {'description': 'Internal server error.'}
        }
    })
    def search_lyrics_route(): # Renamed to avoid conflict
        """Search for lyrics by artist and title"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400
            
            artist = data.get('artist', '').strip()
            title = data.get('title', '').strip()
            force_refresh = data.get('force_refresh', False)
            
            if not artist or not title:
                return jsonify({'error': 'Artist and title are required'}), 400
            
            logger.info(f"API: Searching lyrics for '{artist} - {title}', force_refresh={force_refresh}")
            result = discovery_service_instance.search_lyrics(artist, title, force_refresh)
            if result and result.get('lyrics'):
                return jsonify({'status': 'success', 'data': result})
            else:
                logger.warning(f"API: Lyrics not found for '{artist} - {title}'")
                return jsonify({'status': 'not_found', 'message': 'Lyrics not found'}), 404
                
        except Exception as e:
            logger.error(f"Discovery API error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred', 'details': str(e)}), 500
    
    @app.route('/api/discovery/providers', methods=['GET'])
    @swag_from({
        'tags': ['Discovery'],
        'summary': 'List available lyric providers.',
        'description': 'Returns a list of configured lyric providers and their status.',
        'responses': {
            200: {
                'description': 'List of providers.',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'example': 'success'},
                        'providers': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'name': {'type': 'string', 'example': 'GeniusClient'},
                                    'active': {'type': 'boolean', 'example': True}
                                }
                            }
                        }
                    }
                }
            },
            500: {'description': 'Internal server error.'}
        }
    })
    def get_providers_route(): # Renamed
        """List available providers"""
        try:
            providers_info = [
                {'name': p.__class__.__name__, 'active': True} # Assuming all instantiated providers are active
                for p in discovery_service_instance.providers
            ]
            return jsonify({'status': 'success', 'providers': providers_info})
        except Exception as e:
            logger.error(f"Providers API error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred', 'details': str(e)}), 500
    
    # Analysis routes
    @app.route('/api/analyzer/analyze', methods=['POST'])
    @swag_from({
        'tags': ['Analyzer'],
        'summary': 'Analyze provided lyrics text.',
        'description': 'Analyzes a given block of lyrics using a specified or default analysis framework.',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'id': 'AnalyzeLyricsRequest',
                    'type': 'object',
                    'required': ['lyrics'],
                    'properties': {
                        'lyrics': {'type': 'string', 'description': 'The lyrics text to analyze.', 'example': 'Yesterday, all my troubles seemed so far away...'},
                        'framework': {'type': 'string', 'description': 'The analysis framework to use (e.g., \"vanilla\", \"cinnamon\"). Optional, uses default if not provided.', 'example': 'vanilla'}
                    }
                }
            }
        ],
        'responses': {
            200: {
                'description': 'Analysis successful.',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'example': 'success'},
                        'data': {
                            'type': 'object', 
                            'description': 'The result of the lyrics analysis. Structure depends on the framework used.',
                            'example': {'sentiment': 'positive', 'themes': ['love', 'loss']}
                        }
                    }
                }
            },
            400: {'description': 'Invalid input (e.g., missing lyrics, or framework not found).'},
            500: {'description': 'Internal server error or analysis failure.'}
        }
    })
    def analyze_lyrics_route(): # Renamed
        """Analyze provided lyrics text"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400
            
            lyrics = data.get('lyrics', '').strip()
            framework = data.get('framework') # Optional, will use default if None
            
            if not lyrics:
                return jsonify({'error': 'Lyrics text is required'}), 400
            
            logger.info(f"API: Analyzing lyrics with framework '{framework if framework else app_config_instance.default_framework}'")
            result = analyzer_service_instance.analyze_lyrics(lyrics, framework)
            if result:
                return jsonify({'status': 'success', 'data': result})
            else:
                # This case might occur if analysis internally decides not to return (e.g. LLM error not caught as exception)
                logger.error(f"API: Analysis returned no result for framework '{framework}'.")
                return jsonify({'error': 'Analysis failed to produce a result'}), 500
            
        except ValueError as ve:
             logger.warning(f"Analysis API validation error: {ve}")
             return jsonify({'error': str(ve)}), 400 # e.g. framework not found
        except RuntimeError as re:
            logger.error(f"Analysis API runtime error: {re}", exc_info=True)
            return jsonify({'error': 'Analysis failed due to a runtime issue', 'details': str(re)}), 500
        except Exception as e:
            logger.error(f"Analysis API error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred', 'details': str(e)}), 500
    
    @app.route('/api/analyzer/analyze-song', methods=['POST'])
    @swag_from({
        'tags': ['Analyzer'],
        'summary': 'Discover and analyze song lyrics.',
        'description': 'First discovers lyrics for a given artist and title, then analyzes them using a specified or default framework. If an analysis for the same song is already in progress, it will return a 409 Conflict status.',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'id': 'AnalyzeSongRequest',
                    'type': 'object',
                    'required': ['artist', 'title'],
                    'properties': {
                        'artist': {'type': 'string', 'description': 'The name of the artist.', 'example': 'The Beatles'},
                        'title': {'type': 'string', 'description': 'The title of the song.', 'example': 'Let It Be'},
                        'framework': {'type': 'string', 'description': 'The analysis framework to use. Optional.', 'example': 'cinnamon'},
                        'force_refresh': {'type': 'boolean', 'description': 'Whether to force refresh of lyrics from providers.', 'default': False, 'example': False}
                    }
                }
            }
        ],
        'responses': {
            200: {
                'description': 'Song discovery and analysis successful.',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'status': {'type': 'string', 'example': 'success'},
                        'data': {
                            'type': 'object',
                            'properties': {
                                'analysis': {
                                    'type': 'object',
                                    'description': 'The result of the lyrics analysis.',
                                    'example': {'mood': 'reflective', 'keywords': ['wisdom', 'mother Mary']}
                                },
                                'metadata': {
                                    'type': 'object',
                                    'properties': {
                                        'source': {'type': 'string', 'example': 'genius'},
                                        'artist': {'type': 'string', 'example': 'The Beatles'},
                                        'title': {'type': 'string', 'example': 'Let It Be'}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            400: {'description': 'Invalid input (e.g., missing artist/title).'},
            404: {'description': 'Lyrics not found for the song.'},
            409: {'description': 'Conflict. An analysis for this song is already in progress.'}, # Added 409
            500: {'description': 'Internal server error or analysis failure.'}
        }
    })
    def analyze_song_route(): # Renamed
        """Discover and analyze song lyrics"""
        data = request.get_json()
        if not data:
            logger.warning("API: Analyze song request received with no JSON body.")
            return jsonify({'error': 'JSON body required'}), 400
        
        artist = data.get('artist', '').strip()
        title = data.get('title', '').strip()
        framework_param = data.get('framework') # Renamed to avoid conflict
        force_refresh = data.get('force_refresh', False)
        
        if not artist or not title:
            logger.warning(f"API: Analyze song request missing artist or title. Artist: '{artist}', Title: '{title}'.")
            return jsonify({'error': 'Artist and title are required'}), 400

        # Sanitize artist and title for song_id to be more robust
        # Replace sequences of non-alphanumeric characters with a single underscore
        sanitized_artist = re.sub(r'[^a-zA-Z0-9]+', '_', artist.lower())
        sanitized_title = re.sub(r'[^a-zA-Z0-9]+', '_', title.lower())
        song_id = f"{sanitized_artist}_{sanitized_title}"

        with analysis_lock:
            if song_id in active_analyses:
                logger.info(f"API: Analysis for song '{artist} - {title}' (ID: {song_id}) already in progress. Request rejected.")
                return jsonify({
                    'status': 'conflict', 
                    'message': f"An analysis for '{artist} - {title}' is already in progress. Please wait for it to complete."
                }), 409

            active_analyses.add(song_id)
            logger.info(f"API: Added '{artist} - {title}' (ID: {song_id}) to active analyses. Count: {len(active_analyses)}")

        try:
            logger.info(f"API: Starting discovery and analysis for song '{artist} - {title}' (ID: {song_id}). Framework: '{framework_param}', Force refresh: {force_refresh}")
            
            lyrics_result = discovery_service_instance.search_lyrics(artist, title, force_refresh)
            if not lyrics_result or not lyrics_result.get('lyrics'):
                logger.warning(f"API: Lyrics not found for '{artist} - {title}' (ID: {song_id}).")
                return jsonify({'status': 'not_found', 'message': 'Lyrics not found for song analysis'}), 404
            
            current_framework_name = None
            if isinstance(framework_param, dict) and 'name' in framework_param:
                current_framework_name = framework_param['name']
            elif isinstance(framework_param, str):
                current_framework_name = framework_param
            # If framework_param is None, analyzer_service_instance.analyze_lyrics should use its default.

            logger.info(f"API: Analyzing lyrics for '{artist} - {title}' (ID: {song_id}) with framework: '{current_framework_name if current_framework_name else 'default'}'.")
            analysis_result = analyzer_service_instance.analyze_lyrics(lyrics_result['lyrics'], current_framework_name)
            
            if not analysis_result:
                 logger.error(f"API: Analysis returned no result for '{artist} - {title}' (ID: {song_id}) with framework '{current_framework_name}'.")
                 return jsonify({'error': 'Analysis failed to produce a result for the song'}), 500

            logger.info(f"API: Successfully analyzed '{artist} - {title}' (ID: {song_id}).")
            return jsonify({
                'status': 'success',
                'data': {
                    'analysis': analysis_result,
                    'metadata': {
                        'source': lyrics_result.get('source'),
                        'artist': lyrics_result.get('artist'),
                        'title': lyrics_result.get('title'),
                        **{k: v for k, v in lyrics_result.items() if k not in ['lyrics', 'artist', 'title', 'source']}
                    }
                }
            })
            
        except ValueError as ve:
             logger.warning(f"API: Validation error during analysis of '{artist} - {title}' (ID: {song_id}): {ve}")
             return jsonify({'error': str(ve)}), 400
        except RuntimeError as re_err: # Renamed to avoid conflict with re module
            logger.error(f"API: Runtime error during analysis of '{artist} - {title}' (ID: {song_id}): {re_err}", exc_info=True)
            return jsonify({'error': 'Song analysis failed due to a runtime issue', 'details': str(re_err)}), 500
        except Exception as e:
            logger.error(f"API: Unexpected error during analysis of '{artist} - {title}' (ID: {song_id}): {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred during song analysis', 'details': str(e)}), 500
        finally:
            with analysis_lock:
                if song_id in active_analyses:
                    active_analyses.remove(song_id)
                    logger.info(f"API: Removed '{artist} - {title}' (ID: {song_id}) from active analyses. Count: {len(active_analyses)}")
    
    @app.route('/api/analyzer/frameworks', methods=['GET'])
    def get_frameworks_route(): # Renamed
        """List available analysis frameworks"""
        try:
            frameworks = analyzer_service_instance.get_available_frameworks()
            return jsonify({'status': 'success', 'frameworks': frameworks})
        except Exception as e:
            logger.error(f"Frameworks API error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred', 'details': str(e)}), 500
    
    # Utility routes
    @app.route('/api/cache/clear', methods=['POST'])
    def clear_cache_route(): # Renamed
        """Clear system cache"""
        try:
            data = request.get_json() or {}
            days = data.get('days', 30)
            if not isinstance(days, int) or days <= 0:
                return jsonify({'error': 'Invalid days parameter, must be a positive integer'}), 400
            
            logger.info(f"API: Clearing cache entries older than {days} days.")
            db_instance.clear_old_cache(days)
            return jsonify({'status': 'success', 'message': f'Cache cleared for entries older than {days} days'})
        except Exception as e:
            logger.error(f"Cache clear error: {e}", exc_info=True)
            return jsonify({'error': 'An internal server error occurred', 'details': str(e)}), 500
    
    @app.route('/api/health', methods=['GET'])
    def health_check_route(): # Renamed
        """Health check endpoint"""
        # Basic health check: app is running, config loaded.
        # More advanced checks could ping DB or LLM.
        health_status = {
            'status': 'healthy',
            'llm_provider': app_config_instance.llm_provider if app_config_instance else 'N/A',
            'database_url_configured': bool(app_config_instance.database_url) if app_config_instance else False,
            'log_level': app_config_instance.log_level if app_config_instance else 'N/A'
        }
        # Check if core services are initialized
        if not all([db_instance, discovery_service_instance, analyzer_service_instance, app_config_instance]):
            health_status['status'] = 'degraded'
            health_status['issues'] = 'One or more core services not initialized.'
            return jsonify(health_status), 503

        return jsonify(health_status)
    
    # --- Framework File Route ---
    @app.route('/api/analyzer/frameworks/<string:framework_name>', methods=['GET'])
    @swag_from({
        'tags': ['Analyzer'],
        'summary': 'Get a framework file by name.',
        'description': 'Returns the content of a specific framework file used by the analyzer. '
                       'The framework_name should be the name of the file (e.g., "my_framework.json").',
        'parameters': [
            {
                'name': 'framework_name',
                'in': 'path',
                'type': 'string',
                'required': True,
                'description': 'The name of the framework file to retrieve (e.g., "my_framework.json").'
            }
        ],
        'responses': {
            200: {
                'description': 'Framework file content. The Content-Type will be inferred by Flask.',
                'schema': { 
                    'type': 'file' 
                }
            },
            400: {'description': 'Invalid framework name (e.g., contains path characters).'}, 
            404: {'description': 'Framework file not found.'},
            500: {'description': 'Internal server error while attempting to serve the file.'}
        }
    })
    def get_framework_file_route(framework_name: str):
        """Serves a specific framework file from the pre-configured FRAMEWORK_FILES_DIR."""
        # Security: Ensure framework_name is just a filename and does not contain path components.
        # This check should happen on the raw framework_name from the URL.
        if os.path.basename(framework_name) != framework_name:
            logger.warning(f"API: Invalid framework name (path traversal attempt?): '{framework_name}'")
            return jsonify({'error': 'Invalid framework name. Must be a simple filename.'}), 400

        actual_filename = f"{framework_name}.txt"
        logger.info(f"API: Request for framework: '{framework_name}', attempting to serve file: '{actual_filename}' from directory: '{FRAMEWORK_FILES_DIR}'")

        try:
            # Check if FRAMEWORK_FILES_DIR itself is valid and exists
            if not FRAMEWORK_FILES_DIR or not os.path.isdir(FRAMEWORK_FILES_DIR):
                logger.error(f"API: Framework files directory is not configured or does not exist: {FRAMEWORK_FILES_DIR}")
                return jsonify({'error': 'Server configuration error: framework directory not found.'}), 500

            # Check if the specific file exists to provide a clear JSON 404
            target_file_path = os.path.join(FRAMEWORK_FILES_DIR, actual_filename)
            if not os.path.isfile(target_file_path):
                logger.warning(f"API: Framework file not found: '{actual_filename}' at path: '{target_file_path}'")
                return jsonify({'error': f"Framework file '{actual_filename}' not found."}), 404
            
            # send_from_directory is generally safe and handles Content-Type, ETag, etc.
            return send_from_directory(FRAMEWORK_FILES_DIR, actual_filename, as_attachment=False)
        except Exception as e:
            # Catch any other unexpected errors during file serving.
            logger.error(f"API: Error serving framework file '{actual_filename}': {e}", exc_info=True)
            return jsonify({'error': 'Internal server error while serving file.'}), 500

    return app

# For running directly using `python api/routes.py` (primarily for development)
if __name__ == '__main__':
    # This allows running the Flask app directly.
    # The project root needs to be in PYTHONPATH for 'from src...' imports to work,
    # or the script needs to be run from the project root as 'python -m api.routes'
    # The create_app function handles path resolution for config.yaml assuming it's in project root.
    
    # Ensure project root is in sys.path if running this script directly
    current_script_path = os.path.dirname(os.path.abspath(__file__))
    project_root_main = os.path.abspath(os.path.join(current_script_path, '..'))
    if project_root_main not in sys.path:
        sys.path.insert(0, project_root_main)

    # The config_path for Config.load() inside create_app will be resolved
    # relative to the project root by default if None is passed.
    flask_app = create_app()
    
    # Use host and port from the loaded configuration
    # Ensure app_config_instance is loaded by create_app before accessing it here
    if app_config_instance:
        host = app_config_instance.api_host
        port = app_config_instance.api_port
        debug = app_config_instance.api_debug
        logger.info(f"Starting Flask development server on {host}:{port} with debug={debug}")
        flask_app.run(host=host, port=port, debug=debug)
    else:
        logger.error("Failed to load application configuration. Cannot start development server.")
        # Fallback if config didn't load, though create_app should handle this.
        # flask_app.run(host='0.0.0.0', port=5001, debug=True)

from typing import Optional # For type hinting global vars at top
