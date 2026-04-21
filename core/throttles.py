from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

class ReactionSpamThrottle(UserRateThrottle):
    scope = 'reaction_spam'

class SearchThrottle(UserRateThrottle):
    scope = 'search'

class StrictAuthThrottle(AnonRateThrottle):
    scope = 'strict_auth'