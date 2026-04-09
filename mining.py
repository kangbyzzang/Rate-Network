# ============================================================
# RATE NETWORK - Mining Logic
#
# 총 공급량 300억 = M (기본채굴) + R (추천보너스)
#
# M = 240억  기본 채굴 풀
#   R_base(C) = 5.0 × e^(-k × C)   k = ln(5) / 240억
#
# R = 60억   추천 보너스 풀 (M의 25%)
#   R_bonus = R_base(C) × 활성추천인수 × 0.25
#   (추천 풀 잔량에서 차감, 소진 시 보너스 없음)
#
# 활성 추천인 = 당일 Mining 버튼을 누른 추천인
# ============================================================

import math

R_INITIAL      = 5.0                # 초기 1회 채굴 보상 (코인)
MINING_POOL    = 24_000_000_000     # M: 기본 채굴 풀 (240억)
REFERRAL_POOL  = 6_000_000_000      # R: 추천 보너스 풀 (60억)
TOTAL_SUPPLY   = MINING_POOL + REFERRAL_POOL  # 총 공급량 300억

REFERRAL_BONUS_RATE = 0.25          # 추천인 1인당 25% 보너스

# k = ln(5) / 240억  (기본채굴 풀 기준 반감기)
K = math.log(R_INITIAL) / MINING_POOL   # ≈ 6.699e-11


def calculate_base_reward(total_mined_base: float) -> float:
    """
    기본 채굴 보상: 기본채굴 총량(C)을 기반으로 계산
    total_mined_base = 기본 채굴 풀에서 소진된 양 (추천 보너스 별도)
    """
    if total_mined_base >= MINING_POOL:
        return 0.0
    reward = R_INITIAL * math.exp(-K * total_mined_base)
    return round(reward, 6)


def calculate_referral_bonus(base_reward: float, active_referrals: int,
                              total_mined_referral: float) -> float:
    """
    추천 보너스: 활성 추천인 수 × 25% × 기본보상
    추천 풀(60억)에서 차감, 소진 시 0 반환

    active_referrals     = 당일 Mining 버튼을 누른 내 추천인 수
    total_mined_referral = 지금까지 지급된 추천 보너스 총합
    """
    if active_referrals <= 0:
        return 0.0
    if total_mined_referral >= REFERRAL_POOL:
        return 0.0
    bonus = round(base_reward * active_referrals * REFERRAL_BONUS_RATE, 6)
    # 남은 추천 풀 초과 방지
    remaining_ref_pool = REFERRAL_POOL - total_mined_referral
    return round(min(bonus, remaining_ref_pool), 6)


def get_mining_stats(total_mined_base: float, total_mined_referral: float) -> dict:
    """현재 채굴 현황 통계"""
    base_reward = calculate_base_reward(total_mined_base)
    return {
        "base_reward":             base_reward,
        "total_mined_base":        total_mined_base,
        "total_mined_referral":    total_mined_referral,
        "remaining_mining_pool":   MINING_POOL  - total_mined_base,
        "remaining_referral_pool": REFERRAL_POOL - total_mined_referral,
        "progress_pct":            round((total_mined_base / MINING_POOL) * 100, 4),
        "referral_pool_pct":       round((total_mined_referral / REFERRAL_POOL) * 100, 4),
    }
