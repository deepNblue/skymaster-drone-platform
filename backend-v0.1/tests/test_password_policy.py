"""Unit tests for password policy validator."""
from __future__ import annotations

import pytest

from app.services.password_policy import validate_password, PasswordPolicyError


def test_too_short():
    with pytest.raises(PasswordPolicyError):
        validate_password("Ab1!")


def test_common_rejected():
    with pytest.raises(PasswordPolicyError):
        validate_password("password")  # exact common list hit (also fails classes)
    with pytest.raises(PasswordPolicyError):
        validate_password("welcome1")  # too short and common


def test_missing_classes():
    # Only lowercase + digit = 2 classes < 3
    with pytest.raises(PasswordPolicyError):
        validate_password("abcdefgh12")
    with pytest.raises(PasswordPolicyError):
        validate_password("abcdefghij")


def test_email_localpart_rejected():
    with pytest.raises(PasswordPolicyError):
        validate_password("Duoduo123!", email="duoduo@example.com")


def test_valid_passwords():
    # 3 classes: lower, upper, digit
    validate_password("Abcdefg1")
    # 4 classes with symbol
    validate_password("Abcdef1!")
    # Long random-ish
    validate_password("MyStr0ngP@ssw0rd")


def test_too_long():
    with pytest.raises(PasswordPolicyError):
        validate_password("A1!" + "x" * 300)
