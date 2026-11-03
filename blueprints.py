from flask import Blueprint


_GROUPS = {
    "auth": {
        "index",
        "admin_login",
        "teacher_login",
        "student_login",
        "login",
        "forgot_password",
        "change_password",
        "logout",
    },
    "admin": {
        "admin",
        "admin_students",
        "import_students",
        "import_results",
        "admin_teachers",
        "admin_fees_collected",
        "admin_fees_pending",
        "link_student_login",
        "add_student",
        "save_student",
        "edit_student",
        "update_student",
        "delete_student",
        "teacher_management",
    },
    "academic": {
        "teacher",
        "add_result",
        "save_result",
        "edit_result",
        "update_result",
        "delete_result",
        "gpa",
        "predict",
        "results",
        "exam_registration",
        "save_exam_registration",
        "academic_summary",
        "subjects",
        "add_subject",
        "save_subject",
        "edit_subject",
        "update_subject",
        "delete_subject",
        "analytics",
    },
    "student": {
        "students",
        "profile",
        "generate_hallticket",
        "hall_ticket",
        "hall_ticket_pdf",
    },
    "payments": {
        "fees",
        "confirm_upi",
        "payment",
        "payment_qr_status",
        "save_payment",
        "receipt",
        "receipt_pdf",
    },
}

_BLUEPRINTS = {
    name: Blueprint(name, __name__)
    for name in _GROUPS
}
_FUNCTION_GROUPS = {
    function_name: group
    for group, function_names in _GROUPS.items()
    for function_name in function_names
}


def route(rule, **options):
    def decorator(view):
        group = _FUNCTION_GROUPS.get(view.__name__, "academic")
        return _BLUEPRINTS[group].route(rule, **options)(view)

    return decorator


def register_blueprints(app):
    for blueprint in _BLUEPRINTS.values():
        app.register_blueprint(blueprint)

    for rule in list(app.url_map.iter_rules()):
        if "." not in rule.endpoint:
            continue
        blueprint_name, endpoint = rule.endpoint.split(".", 1)
        if blueprint_name not in _BLUEPRINTS:
            continue
        if endpoint in app.view_functions:
            continue
        view = app.view_functions[rule.endpoint]
        methods = sorted(rule.methods.difference({"HEAD", "OPTIONS"}))
        app.add_url_rule(
            rule.rule,
            endpoint=endpoint,
            view_func=view,
            methods=methods,
        )
