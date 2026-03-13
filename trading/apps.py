from django.apps import AppConfig


class TradingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trading"

    def ready(self):
        import os
        import logging
        logger = logging.getLogger(__name__)

        # Load PPO models
        try:
            from trading import robot_engine
            robot_engine.load_models()
        except Exception as exc:
            logger.warning("Robot models could not be loaded: %s", exc)

        # Start APScheduler only in the reloader child process (RUN_MAIN=true),
        # or unconditionally in production (gunicorn/uwsgi where RUN_MAIN is unset).
        run_main = os.environ.get("RUN_MAIN")
        if run_main == "true" or run_main is None:
            try:
                from trading import robot_engine      
                import importlib
                scheduler = importlib.import_module("trading.scheduler") 
                scheduler.start()
            except Exception as exc:
                logger.warning("Robot scheduler could not be started: %s", exc)