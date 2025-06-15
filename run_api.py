import os
import sys
import logging

# Ensure the 'src' directory is in the Python path
# This allows 'from src.core...' imports within the api.routes module
# when run_api.py is executed from the project root.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now that sys.path is configured, we can import from api.routes
# The create_app function within api.routes will handle its own internal imports (like src.core.config)
import api.routes # Import the module itself

logger = logging.getLogger(__name__) # Use a logger for this script as well

if __name__ == '__main__':
    # The config_path for Config.load() inside create_app will be resolved
    # by create_app itself (defaults to 'config.yaml' in project root).
    # We don't need to pass it explicitly unless we want to override the default search.
    config_file_path = os.path.join(project_root, "config.yaml")

    if not os.path.exists(config_file_path):
        # This is a basic check. create_app also checks and logs.
        print(f"Warning: Configuration file '{config_file_path}' not found. API might use default settings or fail.", file=sys.stderr)

    # Create the Flask app instance. create_app handles config loading and logging setup.
    app = api.routes.create_app(config_path=config_file_path)

    # Access host, port, and debug settings from the globally (within api.routes) loaded config
    # This relies on create_app populating app_config_instance
    if api.routes.app_config_instance:
        host = api.routes.app_config_instance.api_host
        port = api.routes.app_config_instance.api_port
        debug_mode = api.routes.app_config_instance.api_debug
        
        # Configure basic logging for this runner script if not already configured by create_app's call
        # This is a bit redundant if create_app already sets up global logging, but ensures some output.
        if not logging.getLogger().handlers: # Check if root logger has handlers
            log_level_str = api.routes.app_config_instance.log_level.upper()
            log_level = getattr(logging, log_level_str, logging.INFO)
            logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        logger.info(f"Starting LyricMind API server on http://{host}:{port} (Debug mode: {debug_mode})")
        app.run(host=host, port=port, debug=debug_mode)
    else:
        # This case should ideally not be reached if create_app works as expected or raises an error.
        logger.error("Failed to load application configuration via api.routes.app_config_instance. Cannot start API server.")
        print("Error: API configuration not loaded. Check logs. Cannot start server.", file=sys.stderr)
        sys.exit(1)
