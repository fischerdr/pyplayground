#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the validate_k8s_token command."""
import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

# Add project root to path to allow imports from pyplayground
from pyplayground.k8s.validate_k8s_token import validate_k8s_token


class TestValidateK8sToken(unittest.TestCase):
    @patch("pyplayground.k8s.validate_k8s_token.setup_logging")
    @patch("pyplayground.k8s.validate_k8s_token.load_kube_config_auto")
    @patch("pyplayground.k8s.validate_k8s_token.client")
    def test_token_valid(self, mock_k8s_client, mock_load_config, mock_setup_logging):
        """Test the success path where the token is valid."""
        # Arrange
        mock_auth_v1 = MagicMock()
        mock_review_status = MagicMock()
        mock_review_status.authenticated = True
        mock_review_status.user.username = "system:serviceaccount:default:default"
        mock_review_status.user.uid = "some-uid"
        mock_review_status.user.groups = ["system:serviceaccounts"]
        mock_auth_v1.create_token_review.return_value.status = mock_review_status

        mock_core_v1 = MagicMock()
        with patch(
            "pyplayground.k8s.validate_k8s_token.get_service_account_jwt",
            return_value="fake-jwt",
        ):
            mock_k8s_client.CoreV1Api.return_value = mock_core_v1
            mock_k8s_client.AuthenticationV1Api.return_value = mock_auth_v1

            runner = CliRunner()
            result = runner.invoke(
                validate_k8s_token,
                ["--namespace", "default", "--service-account", "default"],
            )

            # Assert
            self.assertEqual(result.exit_code, 0)
            self.assertIn("✔ Token is valid", result.output)
            self.assertIn("system:serviceaccount:default:default", result.output)

    @patch("pyplayground.k8s.validate_k8s_token.setup_logging")
    @patch("pyplayground.k8s.validate_k8s_token.load_kube_config_auto")
    @patch("pyplayground.k8s.validate_k8s_token.get_service_account_jwt", return_value=None)
    def test_token_not_found(self, mock_get_jwt, mock_load_config, mock_setup_logging):
        """Test the case where no JWT can be retrieved for the service account."""
        # Arrange
        runner = CliRunner()
        result = runner.invoke(
            validate_k8s_token,
            ["--namespace", "default", "--service-account", "no-token-sa"],
        )

        # Assert
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Failed to retrieve a JWT", result.output)
        self.assertIn("Kubernetes v1.24+", result.output)

    @patch("pyplayground.k8s.validate_k8s_token.setup_logging")
    @patch("pyplayground.k8s.validate_k8s_token.load_kube_config_auto")
    @patch("pyplayground.k8s.validate_k8s_token.client")
    def test_token_invalid(self, mock_k8s_client, mock_load_config, mock_setup_logging):
        """Test the case where the TokenReview API reports the token is invalid."""
        # Arrange
        mock_auth_v1 = MagicMock()
        mock_review_status = MagicMock()
        mock_review_status.authenticated = False
        mock_review_status.error = "invalid token"
        mock_auth_v1.create_token_review.return_value.status = mock_review_status

        with patch(
            "pyplayground.k8s.validate_k8s_token.get_service_account_jwt",
            return_value="fake-jwt",
        ):
            mock_k8s_client.AuthenticationV1Api.return_value = mock_auth_v1
            runner = CliRunner()

            result = runner.invoke(
                validate_k8s_token,
                ["--namespace", "default", "--service-account", "default"],
            )

            # Assert
            self.assertEqual(result.exit_code, 1)
            self.assertIn("✖ Token is invalid or expired", result.output)
            self.assertIn("Reason: invalid token", result.output)

    @patch("pyplayground.k8s.validate_k8s_token.setup_logging")
    @patch("pyplayground.k8s.validate_k8s_token.load_kube_config_auto")
    @patch("pyplayground.k8s.validate_k8s_token.client")
    def test_api_forbidden_403(self, mock_k8s_client, mock_load_config, mock_setup_logging):
        """Test the case where the API call is forbidden (403)."""
        # Arrange
        from kubernetes.client.rest import ApiException

        mock_auth_v1 = MagicMock()
        mock_auth_v1.create_token_review.side_effect = ApiException(status=403, reason="Forbidden")
        with patch("pyplayground.k8s.validate_k8s_token.get_service_account_jwt", return_value="fake-jwt"):
            mock_k8s_client.AuthenticationV1Api.return_value = mock_auth_v1
            runner = CliRunner()

            result = runner.invoke(
                validate_k8s_token,
                ["--namespace", "default", "--service-account", "default"],
            )

            # Assert
            self.assertEqual(result.exit_code, 1)
            self.assertIn("A Kubernetes API call failed", result.output)
            self.assertIn("Reason: Forbidden", result.output)
            self.assertIn("Check RBAC rules", result.output)


if __name__ == "__main__":
    unittest.main()
