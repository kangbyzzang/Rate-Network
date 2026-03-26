# ============================================================
# RATE NETWORK - Mining Logic
# R(C) = R_initial × e^(-k × C)
# ============================================================

import math

R_INITIAL = 5.0             # 서비스 초기 광고 1회당 리워드 (코인)
TOTAL_SUPPLY = 30_000_000_000  # 전체 채굴 물량 (30억개)

# k 계산: 전체 물량 소진 시 리워드 = 1코인
# 5 × e^(-k × 30B) = 1  →  k = ln(5) / 30B
K = math.log(R_INITIAL) / TOTAL_SUPPLY  # ≈ 1.535e-10


def calculate_reward(total_mined: float) -> float:
    """
    현재 채굴된 총량(C)을 기반으로 광고 1회당 리워드 계산
    """
    if total_mined >= TOTAL_SUPPLY:
        return 0.0
    reward = R_INITIAL * math.exp(-K * total_mined)
    return round(reward, 6)


def calculate_referral_reward(total_mined: float) -> float:
    """
    추천인 보상 = 현재 광고 리워드 × 5회분
    """
    return round(calculate_reward(total_mined) * 5, 6)


def get_mining_stats(total_mined: float) -> dict:
    """
    현재 채굴 현황 통계
    """
    current_reward = calculate_reward(total_mined)
    progress_pct = (total_mined / TOTAL_SUPPLY) * 100
    remaining = TOTAL_SUPPLY - total_mined

    return {
        "current_reward": current_reward,
        "referral_reward": calculate_referral_reward(total_mined),
        "total_mined": total_mined,
        "remaining": remaining,
        "progress_pct": round(progress_pct, 4),
    }
