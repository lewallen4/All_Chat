"""
All_Chat - Wilson Score Lower Bound
Reddit-style ranking that accounts for vote confidence.
A post with 100 upvotes and 0 downvotes ranks lower than
one with 10,000 upvotes and 100 downvotes — correctly.

Formula: Wilson score lower bound at 95% confidence interval.
Reference: https://www.evanmiller.org/how-not-to-sort-by-average-rating.html
"""

import math


def wilson_score_lower_bound(upvotes: int, downvotes: int, confidence: float = 0.95) -> float:
    """
    Calculate the Wilson score lower bound.

    Args:
        upvotes:    Number of positive votes.
        downvotes:  Number of negative votes.
        confidence: Confidence interval (default 95%).

    Returns:
        Float score in [0, 1]. Higher = better ranked.
    """
    n = upvotes + downvotes
    if n == 0:
        return 0.0

    # z-score for confidence interval
    # 95% CI → z = 1.96, 99% CI → z = 2.576
    z_map = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_map.get(confidence, 1.96)

    p_hat = upvotes / n  # observed proportion

    numerator   = p_hat + (z * z) / (2 * n) - z * math.sqrt((p_hat * (1 - p_hat) + (z * z) / (4 * n)) / n)
    denominator = 1 + (z * z) / n

    return numerator / denominator


def hot_score(upvotes: int, downvotes: int, created_at_ts: float) -> float:
    """
    Reddit-style 'hot' score: combines Wilson score with post age.
    Newer posts get a logarithmic boost so fresh content can surface.

    Args:
        created_at_ts: Unix timestamp of post creation.
    """
    import time
    score    = upvotes - downvotes
    order    = math.log(max(abs(score), 1), 10)
    sign     = 1 if score > 0 else (-1 if score < 0 else 0)
    seconds  = created_at_ts - 1134028003  # Reddit epoch offset
    return round(sign * order + seconds / 45000, 7)
