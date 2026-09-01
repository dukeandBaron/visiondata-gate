"""Offline evaluation entrypoints.

Production services must not import this namespace.  Evaluation modules may
invoke public production APIs, but benchmark truth and fixture expectations
remain outside the runtime request contract.
"""
