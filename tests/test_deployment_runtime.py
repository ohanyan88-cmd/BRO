import unittest

from bro_runtime.deployment_runtime import (
    DeploymentObservation,
    DeploymentRejected,
    DeploymentRuntime,
    ReleaseCandidate,
    ReleaseState,
)


class DeploymentRuntimeTests(unittest.TestCase):
    def test_verified_release_promotes_and_reads_back(self):
        candidate = ReleaseCandidate(
            release_ref="release:42",
            artifact_ref="artifact:sha256:abc",
            source_revision="git:abc",
            environment="production",
            verification_ref="evidence:release:42",
        )
        promoted = []
        runtime = DeploymentRuntime()
        result = runtime.promote_and_verify(
            candidate,
            promote=lambda release: promoted.append(release.release_ref),
            read_back=lambda environment: DeploymentObservation(
                environment=environment,
                active_release_ref="release:42",
                active_artifact_ref="artifact:sha256:abc",
                evidence_ref="evidence:deployment:42",
            ),
        )
        self.assertEqual(promoted, ["release:42"])
        self.assertEqual(result.state, ReleaseState.PROMOTED)
        self.assertEqual(result.evidence_ref, "evidence:deployment:42")

    def test_deploy_acknowledgement_cannot_substitute_for_readback(self):
        candidate = ReleaseCandidate(
            "release:42", "artifact:sha256:abc", "git:abc", "production", "evidence:release:42"
        )
        runtime = DeploymentRuntime()
        with self.assertRaisesRegex(DeploymentRejected, "did not confirm"):
            runtime.promote_and_verify(
                candidate,
                promote=lambda _: {"accepted": True},
                read_back=lambda environment: DeploymentObservation(
                    environment, "release:old", "artifact:sha256:old", "evidence:deployment:old"
                ),
            )

    def test_unverified_release_cannot_promote(self):
        candidate = ReleaseCandidate(
            "release:42", "artifact:sha256:abc", "git:abc", "production", "evidence:release:42",
            state=ReleaseState.FAILED,
        )
        with self.assertRaisesRegex(DeploymentRejected, "VERIFIED"):
            DeploymentRuntime().promote_and_verify(candidate, promote=lambda _: None, read_back=lambda _: None)


if __name__ == "__main__":
    unittest.main()
