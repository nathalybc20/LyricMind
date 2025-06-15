import click
import json
import sys
import logging
import os

# Define project_root globally
current_file_path = os.path.abspath(__file__)
current_directory = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_directory, '..'))

# Adjust import paths for CLI context
# This assumes the CLI might be run from the project root, or 'src' is in PYTHONPATH.
try:
    from src.core.config import Config
    from src.core.database import Database
    from src.core.discovery import LyricsDiscovery
    from src.core.analyzer import LyricsAnalyzer
except ImportError:
    # Fallback for scenarios where 'src' is not directly in PYTHONPATH
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    # Re-attempt imports after modifying sys.path
    from src.core.config import Config
    from src.core.database import Database
    from src.core.discovery import LyricsDiscovery
    from src.core.analyzer import LyricsAnalyzer

# Global logger for CLI, configured in cli_entry base command
logger = logging.getLogger("lyrics_cli")

@click.group()
@click.option('--config', 'config_path', default='config.yaml', 
              help='Configuration file path.', type=click.Path(exists=False, dir_okay=False))
@click.option('--log-level', default=None, 
              type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], case_sensitive=False),
              help='Logging level (overrides config).')
@click.pass_context
def cli_entry(ctx, config_path, log_level):
    """Lyrics Analysis System CLI"""
    ctx.ensure_object(dict)
    
    # Resolve config_path: if not absolute, assume relative to current working directory or project root
    if not os.path.isabs(config_path):
        # Try CWD first
        potential_cwd_path = os.path.join(os.getcwd(), config_path)
        # Then try project root (using global project_root)
        # project_root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) # Replaced by global project_root
        potential_project_root_path = os.path.join(project_root, config_path) # Use global project_root
        
        if os.path.exists(potential_cwd_path):
            config_path = potential_cwd_path
        elif os.path.exists(potential_project_root_path):
            config_path = potential_project_root_path
        # If neither exists, Config.load() will handle it and use defaults or error out

    # Load configuration
    try:
        app_config = Config.load(config_path)
        ctx.obj['config'] = app_config
    except Exception as e:
        click.echo(f"Error loading configuration from '{config_path}': {e}", err=True)
        # Fallback to default config if loading fails, so some commands might still work partially
        # or provide more graceful errors later.
        ctx.obj['config'] = Config() # Load with defaults
        click.echo("Warning: Using default configuration due to loading error.", err=True)

    # Setup logging - use log_level from CLI option if provided, else from config, else default INFO
    effective_log_level_str = log_level or ctx.obj['config'].log_level or 'INFO'
    effective_log_level = getattr(logging, effective_log_level_str.upper(), logging.INFO)
    
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    # Basic config to console
    logging.basicConfig(level=effective_log_level, format=log_format, stream=sys.stderr)
    
    # File logging if configured
    if ctx.obj['config'].log_file:
        try:
            # Resolve log_file path relative to project root if not absolute
            log_file_path_cfg = ctx.obj['config'].log_file
            if not os.path.isabs(log_file_path_cfg):
                log_file_path_abs = os.path.join(project_root, log_file_path_cfg) # Use global project_root
            else:
                log_file_path_abs = log_file_path_cfg
            
            os.makedirs(os.path.dirname(log_file_path_abs), exist_ok=True)
            file_handler = logging.FileHandler(log_file_path_abs)
            file_handler.setLevel(effective_log_level)
            file_handler.setFormatter(logging.Formatter(log_format))
            logging.getLogger().addHandler(file_handler) # Add to root logger
            logger.info(f"CLI logging also to file: {log_file_path_abs}")
        except Exception as e:
            logger.error(f"Failed to set up file logger at {ctx.obj['config'].log_file}: {e}")

    logger.info(f"CLI Initialized. Log level: {effective_log_level_str}. Config path: {config_path}")

    # Initialize Database after config and logging are set up
    try:
        ctx.obj['database'] = Database(ctx.obj['config'].database_url)
    except Exception as e:
        logger.error(f"Failed to initialize database with URL {ctx.obj['config'].database_url}: {e}", exc_info=True)
        click.echo(f"Error: Could not initialize database: {e}. Some commands may fail.", err=True)
        ctx.obj['database'] = None # Ensure it's set, even if to None

# Helper to get services, ensures they are initialized if DB is available
def _get_services(ctx):
    config = ctx.obj['config']
    database = ctx.obj.get('database') # Use .get to handle if DB init failed

    if database is None:
        click.echo("Database not available. Cannot perform operation.", err=True)
        sys.exit(1)
        
    discovery = LyricsDiscovery(config, database)
    analyzer = LyricsAnalyzer(config, database)
    return discovery, analyzer, database

@cli_entry.command()
@click.argument('artist')
@click.argument('title')
@click.option('--force-refresh', is_flag=True, help='Force refresh cache, fetch from providers.')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json'], case_sensitive=False), default='text',
              help='Output format.')
@click.pass_context
def search(ctx, artist, title, force_refresh, output_format):
    """Search for song lyrics by ARTIST and TITLE."""
    logger.info(f"CLI: search command - Artist: {artist}, Title: {title}, Force: {force_refresh}, Format: {output_format}")
    discovery, _, _ = _get_services(ctx)
    
    try:
        result = discovery.search_lyrics(artist, title, force_refresh)
        if result and result.get('lyrics'):
            if output_format == 'json':
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"Lyrics for: {result.get('artist', artist)} - {result.get('title', title)}")
                click.echo(f"Source: {result.get('source', 'N/A')}")
                if result.get('track_url'):
                    click.echo(f"URL: {result.get('track_url')}")
                if result.get('confidence'):
                    click.echo(f"Confidence: {result.get('confidence')}")
                click.echo("\n" + result['lyrics'])
        else:
            click.echo(f"Lyrics not found for '{artist} - {title}'.", err=True)
            sys.exit(1)
    except Exception as e:
        logger.error(f"CLI search error: {e}", exc_info=True)
        click.echo(f"Error during search: {e}", err=True)
        sys.exit(1)

@cli_entry.command()
@click.argument('lyrics_file', type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option('--framework', help='Analysis framework to use (e.g., vanilla). Uses default if not set.')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json'], case_sensitive=False), default='json',
              help='Output format.')
@click.pass_context
def analyze(ctx, lyrics_file, framework, output_format):
    """Analyze lyrics from LYRICS_FILE."""
    logger.info(f"CLI: analyze command - File: {lyrics_file}, Framework: {framework}, Format: {output_format}")
    _, analyzer, _ = _get_services(ctx)
    
    try:
        with open(lyrics_file, 'r', encoding='utf-8') as f:
            lyrics = f.read().strip()
        
        if not lyrics:
            click.echo("No lyrics content found in the file.", err=True)
            sys.exit(1)
        
        result = analyzer.analyze_lyrics(lyrics, framework)
        if result:
            if output_format == 'json':
                click.echo(json.dumps(result, indent=2))
            else: # text output
                click.echo(f"Analysis Result (Framework: {framework or ctx.obj['config'].default_framework}):")
                for key, value in result.items():
                    click.echo(f"  {str(key).replace('_', ' ').title()}: {value}")
        else:
            click.echo("Analysis failed to produce a result.", err=True)
            sys.exit(1)
                
    except ValueError as ve:
        logger.warning(f"CLI analyze validation error: {ve}")
        click.echo(f"Error: {ve}", err=True)
        sys.exit(1)
    except RuntimeError as re:
        logger.error(f"CLI analyze runtime error: {re}", exc_info=True)
        click.echo(f"Runtime Error during analysis: {re}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"CLI analyze error: {e}", exc_info=True)
        click.echo(f"An unexpected error occurred: {e}", err=True)
        sys.exit(1)

@cli_entry.command("analyze-song")
@click.argument('artist')
@click.argument('title')
@click.option('--framework', help='Analysis framework to use. Uses default if not set.')
@click.option('--force-refresh', is_flag=True, help='Force refresh lyrics cache.')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json'], case_sensitive=False), default='json',
              help='Output format.')
@click.pass_context
def analyze_song(ctx, artist, title, framework, force_refresh, output_format):
    """Discover and then analyze lyrics for a SONG by ARTIST and TITLE."""
    logger.info(f"CLI: analyze-song - Artist: {artist}, Title: {title}, Framework: {framework}, Force: {force_refresh}")
    discovery, analyzer, _ = _get_services(ctx)
    
    try:
        # Discover lyrics
        lyrics_result = discovery.search_lyrics(artist, title, force_refresh)
        if not lyrics_result or not lyrics_result.get('lyrics'):
            click.echo(f"Lyrics not found for '{artist} - {title}'. Cannot analyze.", err=True)
            sys.exit(1)
        
        click.echo(f"Found lyrics for '{artist} - {title}' from source: {lyrics_result['source']}. Analyzing...", err=True)
        # Analyze lyrics
        analysis_result = analyzer.analyze_lyrics(lyrics_result['lyrics'], framework)
        
        if not analysis_result:
            click.echo("Analysis failed to produce a result for the song.", err=True)
            sys.exit(1)

        output_data = {
            'analysis': analysis_result,
            'metadata': {
                'artist': lyrics_result.get('artist', artist),
                'title': lyrics_result.get('title', title),
                'source': lyrics_result.get('source'),
                **{k: v for k, v in lyrics_result.items() if k not in ['lyrics', 'artist', 'title', 'source']}
            }
        }
        
        if output_format == 'json':
            click.echo(json.dumps(output_data, indent=2))
        else: # text output
            click.echo(f"\n--- Analysis for '{artist} - {title}' ---")
            click.echo(f"Lyrics Source: {output_data['metadata']['source']}")
            click.echo(f"Framework Used: {framework or ctx.obj['config'].default_framework}")
            click.echo("--- Result ---")
            for key, value in analysis_result.items():
                click.echo(f"  {str(key).replace('_', ' ').title()}: {value}")
                
    except ValueError as ve:
        logger.warning(f"CLI analyze-song validation error: {ve}")
        click.echo(f"Error: {ve}", err=True)
        sys.exit(1)
    except RuntimeError as re:
        logger.error(f"CLI analyze-song runtime error: {re}", exc_info=True)
        click.echo(f"Runtime Error during song analysis: {re}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"CLI analyze-song error: {e}", exc_info=True)
        click.echo(f"An unexpected error occurred: {e}", err=True)
        sys.exit(1)

@cli_entry.command()
@click.pass_context
def providers(ctx):
    """List available and configured lyrics providers."""
    logger.info("CLI: providers command")
    discovery, _, _ = _get_services(ctx)
    
    if not discovery.providers:
        click.echo("No lyrics providers seem to be active or configured.")
        click.echo("Check your genius_token and musixmatch_api_key in the config file.")
        return

    click.echo("Configured and Active Lyrics Providers (in order of preference):")
    for i, provider_instance in enumerate(discovery.providers):
        click.echo(f"  {i+1}. {provider_instance.__class__.__name__}")

@cli_entry.command()
@click.pass_context
def frameworks(ctx):
    """List available analysis frameworks."""
    logger.info("CLI: frameworks command")
    _, analyzer, _ = _get_services(ctx)
    
    available_frameworks = analyzer.get_available_frameworks()
    if not available_frameworks:
        click.echo("No analysis frameworks found. Ensure .txt files exist in the frameworks directory.")
        click.echo(f"Expected directory: {os.path.join(ctx.obj['config'].framework_directory)}")
        return

    click.echo("Available Analysis Frameworks:")
    for fw in available_frameworks:
        click.echo(f"  - {fw['name']} (Version: {fw['version']})")

@cli_entry.command("clear-cache")
@click.option('--days', type=int, default=30, show_default=True, help='Clear cache entries older than N days.')
@click.pass_context
def clear_cache_cmd(ctx, days):
    """Clear system's lyrics and analysis cache."""
    logger.info(f"CLI: clear-cache command, Days: {days}")
    _, _, database = _get_services(ctx)
    
    if days <= 0:
        click.echo("Error: 'days' must be a positive integer.", err=True)
        sys.exit(1)

    try:
        database.clear_old_cache(days)
        click.echo(f"Successfully cleared cache entries older than {days} days.")
    except Exception as e:
        logger.error(f"CLI clear-cache error: {e}", exc_info=True)
        click.echo(f"Error clearing cache: {e}", err=True)
        sys.exit(1)

@cli_entry.command("test-llm")
@click.pass_context
def test_llm_cmd(ctx):
    """Test connectivity and basic functionality of the configured LLM."""
    logger.info("CLI: test-llm command")
    config = ctx.obj['config']
    _, analyzer, _ = _get_services(ctx)
    
    click.echo(f"Attempting to test LLM: {config.llm_provider} - {config.llm_model}")
    if config.llm_provider == 'openai' and not config.openai_api_key:
        click.echo("OpenAI provider selected, but API key is missing in config.", err=True)
        sys.exit(1)
    if config.llm_provider == 'anthropic' and not config.anthropic_api_key:
        click.echo("Anthropic provider selected, but API key is missing in config.", err=True)
        sys.exit(1)

    try:
        # Use a very simple, short lyric and a default framework (or vanilla if default isn't loaded)
        test_lyrics = "Sun is shining, weather is sweet. Makes you wanna move your dancing feet."
        framework_to_test = config.default_framework
        if framework_to_test not in analyzer.frameworks:
            if 'vanilla' in analyzer.frameworks:
                framework_to_test = 'vanilla'
            else: # If no frameworks loaded at all
                click.echo("No analysis frameworks loaded (e.g. vanilla.txt). Cannot perform LLM test.", err=True)
                click.echo(f"Please ensure framework files are in: {analyzer._resolve_framework_dir()}", err=True)
                sys.exit(1)

        click.echo(f"Using framework '{framework_to_test}' for the test.")
        # Temporarily disable caching for this test to ensure LLM is hit
        original_get_cached_analysis = analyzer.db.get_cached_analysis
        analyzer.db.get_cached_analysis = lambda *args, **kwargs: None
        
        result = analyzer.analyze_lyrics(test_lyrics, framework_to_test)
        
        # Restore caching function
        analyzer.db.get_cached_analysis = original_get_cached_analysis

        if result:
            click.echo("LLM test successful!")
            click.echo(f"Provider: {config.llm_provider}, Model: {config.llm_model}")
            click.echo("Test analysis result (condensed):")
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("LLM test completed, but no result was returned from analysis.", err=True)
            sys.exit(1)
        
    except ConnectionError as ce:
        logger.error(f"CLI LLM connection error: {ce}", exc_info=True)
        click.echo(f"LLM Connection Test Failed: {ce}. Check your API key, endpoint, and network.", err=True)
        sys.exit(1)
    except ValueError as ve: # E.g. API key missing, framework not found
        logger.warning(f"CLI LLM test validation error: {ve}")
        click.echo(f"LLM Test Failed (Configuration/Input Error): {ve}", err=True)
        sys.exit(1)
    except RuntimeError as rte:
        logger.error(f"CLI LLM test runtime error: {rte}", exc_info=True)
        click.echo(f"LLM Test Failed (Runtime Error): {rte}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"CLI LLM test unexpected error: {e}", exc_info=True)
        click.echo(f"LLM Test Failed (Unexpected Error): {e}", err=True)
        sys.exit(1)

if __name__ == '__main__':
    # This allows running the CLI directly, e.g., `python cli/main.py search ...`
    # Ensure project root is in sys.path for 'from src...' imports
    # Define project_root locally for this block to ensure it's available
    _current_file_path = os.path.abspath(__file__)
    _current_directory = os.path.dirname(_current_file_path)
    _project_root_local = os.path.abspath(os.path.join(_current_directory, '..'))
    if _project_root_local not in sys.path:
        sys.path.insert(0, _project_root_local)
    cli_entry(prog_name='python -m cli.main') # Use a prog_name for better help messages
