from . import auth, availability, meetings, monitoring, users

ROUTERS = [
    auth.router,
    users.router,
    availability.router,
    meetings.router,
    monitoring.router,
    monitoring.page_router,
]

__all__ = ["ROUTERS"]
