import time
from edgedash.sources.base import Source, register
from edgedash.sources.http import get_json, SourceError

# Module-level constants
_API_URL = "https://www.arbeitnow.com/api/job-board-api"
_MAX_PAGES = 5
_MIN_RESULTS_BEFORE_LOCATION_RELAX = 5
_REQ_DELAY = 1.0

@register
class ArbeitnowSource(Source):
    name = "arbeitnow"

    def fetch(self, config) -> list[dict]:
        """Fetch jobs from the Arbeitnow API with proper pagination structures."""
        keyword_matched_pool = []
        raw_count = 0
        page = 1

        while page <= _MAX_PAGES:
            try:
                params = {"page": page}
                response = get_json(_API_URL, params=params)
                
                results = response.get("data", [])
                if not results:
                    break
                
                raw_count += len(results)
                
                page_filtered = self._filter_by_keywords(results, config)
                keyword_matched_pool.extend(page_filtered)
                
                page += 1
                time.sleep(_REQ_DELAY)  # Rule 14 Rate limit
                
            except SourceError as e:
                print(f"[ArbeitnowSource] Error fetching page {page}: {e}")
                break

        print(f"[ArbeitnowSource] fetched {raw_count} raw listing(s) across 5 page(s)")

        final_results = self._filter_by_location(keyword_matched_pool, config)
        
        if len(final_results) < _MIN_RESULTS_BEFORE_LOCATION_RELAX:
            print(f"[ArbeitnowSource] location filter left only {len(final_results)} result(s) – relaxing to include remote/nearby roles ({len(keyword_matched_pool)} keyword matches kept)")
            final_results = keyword_matched_pool

        normalized = self._normalize(final_results)
        kw_display = str(config.keywords[:3]).replace("]", ", ...]") if len(config.keywords) > 3 else str(config.keywords)
        print(f"[ArbeitnowSource] {len(normalized)} listing(s) survived filtering (keywords={kw_display}, city='{config.target_city}')")
        
        return normalized

    @staticmethod
    def _filter_by_keywords(results: list[dict], config) -> list[dict]:
        filtered = []
        keywords_lower = [k.lower() for k in config.keywords]
        for result in results:
            title = (result.get("title") or "").lower()
            description = (result.get("description") or "").lower()
            if any(kw in title or kw in description for kw in keywords_lower):
                filtered.append(result)
        return filtered

    @staticmethod
    def _filter_by_location(results: list[dict], config) -> list[dict]:
        filtered = []
        city_lower = config.target_city.lower()
        for result in results:
            location = (result.get("location") or "").lower()
            if city_lower in location:
                filtered.append(result)
        return filtered

    @staticmethod
    def _normalize(results: list[dict]) -> list[dict]:
        normalized = []
        for result in results:
            normalized.append({
                "source": "arbeitnow",
                "external_id": result.get("slug") or str(result.get("id")) or None,
                "title": result.get("title") or None,
                "company": result.get("company_name") or None,
                "location": result.get("location") or None,
                "url": result.get("url") or None,
                "description": result.get("description") or None,
                "posted_at": result.get("posted_at") or None,
                "raw": result
            })
        return normalized
