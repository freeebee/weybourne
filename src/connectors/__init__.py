"""Integration layer for the Weybourne Investment Connector.

Each connector talks to an external system (Microsoft Graph for Outlook mail &
calendar, Notion for the main databases) and degrades gracefully to a
mock/demo mode when its credentials are not configured, so the app is always
runnable and demonstrable.
"""
