def __getattr__(name):
    if name =='guardian':
        from vnai.beam.quota import guardian
        return guardian
    elif name =='optimize':
        from vnai.beam.quota import optimize
        return optimize
    elif name =='collector':
        from vnai.beam.metrics import collector
        return collector
    elif name =='capture':
        from vnai.beam.metrics import capture
        return capture
    elif name =='monitor':
        from vnai.beam.pulse import monitor
        return monitor
    elif name =='get_auth_state_manager':
        from vnai.beam.auth import get_auth_state_manager
        return get_auth_state_manager
    elif name =='AuthStateManager':
        from vnai.beam.auth import AuthStateManager
        return AuthStateManager
    elif name =='authenticator':
        from vnai.beam.auth import authenticator
        return authenticator
    raise AttributeError(f"module 'vnai.beam' has no attribute '{name}'")