# ============================================================
# RATE NETWORK - Firebase Firestore REST API Client
# ============================================================

import requests
from typing import Optional, Dict, Any, List
from config import FIREBASE_API_KEY, FIREBASE_PROJECT_ID

BASE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    f"/databases/(default)/documents"
)


# ── Firestore 데이터 변환 헬퍼 ──────────────────────────────

def to_firestore(value: Any) -> dict:
    if isinstance(value, bool):
        return {"booleanValue": value}
    elif isinstance(value, int):
        return {"integerValue": str(value)}
    elif isinstance(value, float):
        return {"doubleValue": value}
    elif isinstance(value, str):
        return {"stringValue": value}
    elif isinstance(value, list):
        return {"arrayValue": {"values": [to_firestore(v) for v in value]}}
    elif isinstance(value, dict):
        return {"mapValue": {"fields": {k: to_firestore(v) for k, v in value.items()}}}
    elif value is None:
        return {"nullValue": None}
    return {"stringValue": str(value)}


def from_firestore(value: dict) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    elif "integerValue" in value:
        return int(value["integerValue"])
    elif "doubleValue" in value:
        return float(value["doubleValue"])
    elif "booleanValue" in value:
        return value["booleanValue"]
    elif "arrayValue" in value:
        items = value["arrayValue"].get("values", [])
        return [from_firestore(v) for v in items]
    elif "mapValue" in value:
        fields = value["mapValue"].get("fields", {})
        return {k: from_firestore(v) for k, v in fields.items()}
    elif "nullValue" in value:
        return None
    return None


def doc_to_dict(doc_data: dict) -> Optional[dict]:
    if not doc_data or "fields" not in doc_data:
        return None
    return {k: from_firestore(v) for k, v in doc_data["fields"].items()}


# ── FirebaseClient 클래스 ───────────────────────────────────

class FirebaseClient:

    def _url(self, collection: str, doc_id: str) -> str:
        return f"{BASE_URL}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"

    # ── 기본 CRUD ──────────────────────────────────────────

    def get_document(self, collection: str, doc_id: str) -> Optional[dict]:
        resp = requests.get(self._url(collection, doc_id))
        if resp.status_code == 200:
            return doc_to_dict(resp.json())
        return None

    def set_document(self, collection: str, doc_id: str, data: dict) -> bool:
        """문서 전체 덮어쓰기"""
        fields = {k: to_firestore(v) for k, v in data.items()}
        resp = requests.patch(self._url(collection, doc_id), json={"fields": fields})
        return resp.status_code == 200

    def update_document(self, collection: str, doc_id: str, data: dict) -> bool:
        """특정 필드만 부분 업데이트"""
        mask = "&".join([f"updateMask.fieldPaths={k}" for k in data.keys()])
        url = f"{BASE_URL}/{collection}/{doc_id}?key={FIREBASE_API_KEY}&{mask}"
        fields = {k: to_firestore(v) for k, v in data.items()}
        resp = requests.patch(url, json={"fields": fields})
        return resp.status_code == 200

    def get_collection(self, collection: str) -> List[dict]:
        """컬렉션 전체 문서 조회"""
        url = f"{BASE_URL}/{collection}?key={FIREBASE_API_KEY}"
        resp = requests.get(url)
        if resp.status_code != 200:
            return []
        results = []
        for doc in resp.json().get("documents", []):
            doc_id = doc["name"].split("/")[-1]
            parsed = doc_to_dict(doc)
            if parsed is not None:
                parsed["_id"] = doc_id
                results.append(parsed)
        return results

    # ── 유저 관련 ──────────────────────────────────────────

    def get_user(self, user_id: str) -> Optional[dict]:
        return self.get_document("users", str(user_id))

    def create_user(self, user_id: str, data: dict) -> bool:
        return self.set_document("users", str(user_id), data)

    def update_user(self, user_id: str, data: dict) -> bool:
        return self.update_document("users", str(user_id), data)

    def get_all_users(self) -> List[dict]:
        return self.get_collection("users")

    def find_user_by_referral_code(self, code: str) -> Optional[dict]:
        """추천인 코드로 유저 검색"""
        users = self.get_all_users()
        for user in users:
            if user.get("referral_code", "").upper() == code.upper():
                return user
        return None

    # ── 글로벌 통계 ────────────────────────────────────────

    def get_global_stats(self) -> dict:
        stats = self.get_document("global", "stats")
        if not stats:
            init = {"total_mined": 0.0, "total_mined_base": 0.0, "total_mined_referral": 0.0}
            self.set_document("global", "stats", init)
            return init
        # 구버전 호환: total_mined_base 없으면 total_mined로 대체
        if "total_mined_base" not in stats:
            stats["total_mined_base"] = stats.get("total_mined", 0.0)
        if "total_mined_referral" not in stats:
            stats["total_mined_referral"] = 0.0
        return stats

    def add_to_total_mined(self, base_amount: float, referral_amount: float = 0.0):
        """기본채굴 풀 + 추천보너스 풀 각각 업데이트"""
        stats = self.get_global_stats()
        new_base     = stats.get("total_mined_base", 0.0)     + base_amount
        new_referral = stats.get("total_mined_referral", 0.0) + referral_amount
        new_total    = new_base + new_referral
        self.update_document("global", "stats", {
            "total_mined":          new_total,
            "total_mined_base":     new_base,
            "total_mined_referral": new_referral,
        })

    def get_users_referred_by(self, referrer_id: str) -> List[dict]:
        """특정 유저가 추천한 유저 목록 조회"""
        users = self.get_all_users()
        return [u for u in users if u.get("referred_by") == referrer_id]

    # ── 광고 세션 검증 (Postback) ──────────────────────────

    def store_verified_ymid(self, ymid: str) -> bool:
        """Monetag postback 수신 시 ymid를 검증됨으로 저장 (10분 TTL)"""
        import time
        data = {
            "verified": True,
            "expires_at": int(time.time()) + 600,  # 10분 후 만료
        }
        return self.set_document("verified_ads", ymid, data)

    # ── 광고 시청 로그 (미지급 자동 복구용) ───────────────────

    def create_watch_log(self, ymid: str, user_id: str, timestamp: str) -> bool:
        """광고 시청 직후 pending 기록 생성"""
        data = {
            "user_id": user_id,
            "ymid": ymid,
            "timestamp": timestamp,
            "status": "pending",
            "retry_count": 0,
        }
        return self.set_document("ad_watch_log", ymid, data)

    def complete_watch_log(self, ymid: str, rewarded_at: str) -> bool:
        """보상 지급 완료 시 status → completed"""
        return self.update_document("ad_watch_log", ymid, {
            "status": "completed",
            "rewarded_at": rewarded_at,
        })

    def fail_watch_log(self, ymid: str) -> bool:
        """최대 재시도 초과 시 status → failed"""
        return self.update_document("ad_watch_log", ymid, {"status": "failed"})

    def increment_watch_log_retry(self, ymid: str, retry_count: int) -> bool:
        return self.update_document("ad_watch_log", ymid, {"retry_count": retry_count})

    def get_watch_log(self, ymid: str) -> Optional[dict]:
        return self.get_document("ad_watch_log", ymid)

    def get_pending_watch_logs(self) -> List[dict]:
        """status == pending 인 로그 전체 조회"""
        return [doc for doc in self.get_collection("ad_watch_log")
                if doc.get("status") == "pending"]

    def check_and_consume_ymid(self, ymid: str) -> bool:
        """ymid가 검증됐는지 확인 후 소비(삭제). 유효하면 True 반환"""
        import time
        import requests as req
        doc = self.get_document("verified_ads", ymid)
        if not doc:
            return False
        if not doc.get("verified"):
            return False
        if doc.get("expires_at", 0) < int(time.time()):
            # 만료된 ymid 삭제
            url = f"{BASE_URL}/verified_ads/{ymid}?key={FIREBASE_API_KEY}"
            req.delete(url)
            return False
        # 소비 처리 - 재사용 방지를 위해 즉시 삭제
        url = f"{BASE_URL}/verified_ads/{ymid}?key={FIREBASE_API_KEY}"
        req.delete(url)
        return True
