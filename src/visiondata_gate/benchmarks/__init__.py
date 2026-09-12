"""Offline evaluation entrypoints.

Production decision and execution paths must not consume benchmark fixtures or
truth. Read-only reviewer projections may import benchmark validators and
immutable protocol constants, while fixture expectations remain outside the
runtime request contract.
"""
