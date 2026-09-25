from scripts.regenerate_matchbalance_samples import verify_committed_samples


def test_committed_matchbalance_samples_match_the_renderer_manifest():
    verify_committed_samples()
