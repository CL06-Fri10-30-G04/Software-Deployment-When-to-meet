from . import auth, availability, meetings, users

ROUTERS = [auth.router, users.router, availability.router, meetings.router]

__all__ = ["ROUTERS"]
