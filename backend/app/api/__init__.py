from . import auth, availability, calendar, meetings, monitoring, users

ROUTERS = [
    auth.router,
    users.router,
    availability.router,
    meetings.router,
    calendar.router,
    monitoring.router,
    monitoring.page_router,
]

__all__ = ["ROUTERS"]
