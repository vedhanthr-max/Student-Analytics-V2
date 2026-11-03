from collections.abc import Mapping

from config import DEBUG, get_secret_key
from .admin import ENDPOINTS as ADMIN_ENDPOINTS, blueprint as admin_blueprint
from .analytics import ENDPOINTS as ANALYTICS_ENDPOINTS, blueprint as analytics_blueprint
from .auth import ENDPOINTS as AUTH_ENDPOINTS, blueprint as auth_blueprint
from .payments import ENDPOINTS as PAYMENT_ENDPOINTS, blueprint as payments_blueprint
from .student import ENDPOINTS as STUDENT_ENDPOINTS, blueprint as student_blueprint
from .teacher import ENDPOINTS as TEACHER_ENDPOINTS, blueprint as teacher_blueprint

_BLUEPRINTS = {
    "auth": (auth_blueprint, AUTH_ENDPOINTS),
    "admin": (admin_blueprint, ADMIN_ENDPOINTS),
    "teacher": (teacher_blueprint, TEACHER_ENDPOINTS),
    "student": (student_blueprint, STUDENT_ENDPOINTS),
    "payments": (payments_blueprint, PAYMENT_ENDPOINTS),
    "analytics": (analytics_blueprint, ANALYTICS_ENDPOINTS),
}
_FUNCTION_GROUPS = {
    endpoint: group
    for group, (_, endpoints) in _BLUEPRINTS.items()
    for endpoint in endpoints
}
_legacy_app = None


def route(rule, **options):
    def decorator(view):
        group = _FUNCTION_GROUPS.get(view.__name__, "teacher")
        return _BLUEPRINTS[group][0].route(rule, **options)(view)

    return decorator


def register_blueprints(app):
    for blueprint, _ in _BLUEPRINTS.values():
        if blueprint.name not in app.blueprints:
            app.register_blueprint(blueprint)

    for rule in list(app.url_map.iter_rules()):
        if "." not in rule.endpoint:
            continue
        blueprint_name, endpoint = rule.endpoint.split(".", 1)
        if blueprint_name not in _BLUEPRINTS or endpoint in app.view_functions:
            continue
        view = app.view_functions[rule.endpoint]
        methods = sorted(rule.methods.difference({"HEAD", "OPTIONS"}))
        app.add_url_rule(rule.rule, endpoint=endpoint, view_func=view, methods=methods)


def create_app(config=None):
    global _legacy_app
    if _legacy_app is None:
        from . import legacy

        _legacy_app = legacy.app
        register_blueprints(_legacy_app)
    debug = _legacy_app.config.get("DEBUG", DEBUG)
    if config:
        if isinstance(config, Mapping):
            _legacy_app.config.update(config)
        else:
            _legacy_app.config.from_object(config)
        debug = _legacy_app.config.get("DEBUG", debug)
    _legacy_app.config["SECRET_KEY"] = get_secret_key(debug=debug)
    return _legacy_app


app = create_app()
