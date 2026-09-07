from edgedash.agents.base import AgentResult


class MockFetcher:
    name = "MockFetcher"

    @staticmethod
    def run(config, storage) -> AgentResult:
        """Fetch 12 fake listings. 4 are identical across runs for dedup proof."""

        # 4 listings that repeat every run (same stable ID)
        stable_listings = [
            {
                "source": "linkedin",
                "url": "https://linkedin.com/jobs/1001",
                "title": "Senior Data Analyst",
                "company": "TechCorp India",
                "location": config.target_city,
                "description": "5+ years experience with Python, SQL, and Tableau. Lead data initiatives.",
                "posted_at": "2026-08-20T10:00:00Z",
            },
            {
                "source": "linkedin",
                "url": "https://linkedin.com/jobs/1002",
                "title": "Data Analyst - Growth",
                "company": "StartupXyz",
                "location": config.target_city,
                "description": "Join our team! Python, SQL, and analytics. Remote friendly.",
                "posted_at": "2026-08-19T14:30:00Z",
            },
            {
                "source": "indeed",
                "url": "https://indeed.com/jobs/5001",
                "title": "Analytics Engineer",
                "company": "CloudBase",
                "location": config.target_city,
                "description": "We need SQL experts and Python developers. ETL pipelines, data warehousing.",
                "posted_at": "2026-08-21T09:15:00Z",
            },
            {
                "source": "indeed",
                "url": "https://indeed.com/jobs/5002",
                "title": "BI Developer",
                "company": "FinanceHub",
                "location": config.target_city,
                "description": "Tableau, Power BI, SQL reporting. 3-4 years preferred.",
                "posted_at": "2026-08-18T11:45:00Z",
            },
        ]

        # 8 unique listings (fresh on every run)
        unique_listings = [
            {
                "source": "naukri",
                "url": "https://naukri.com/jobs/2001",
                "title": "Junior Data Analyst",
                "company": "RetailCo",
                "location": config.target_city,
                "description": "Entry-level role. Learn SQL, Excel, and basic Python scripting.",
                "posted_at": "2026-08-22T08:00:00Z",
            },
            {
                "source": "naukri",
                "url": "https://naukri.com/jobs/2002",
                "title": "Data Scientist",
                "company": "ResearchLab",
                "location": config.target_city,
                "description": "Python, ML libraries, SQL databases. PhD preferred.",
                "posted_at": "2026-08-22T09:30:00Z",
            },
            {
                "source": "internshala",
                "url": "https://internshala.com/jobs/3001",
                "title": "Analytics Intern",
                "company": "EdTechStartup",
                "location": config.target_city,
                "description": "Gain hands-on experience with Python, SQL, data visualization.",
                "posted_at": "2026-08-22T10:00:00Z",
            },
            {
                "source": "linkedin",
                "url": "https://linkedin.com/jobs/1003",
                "title": "Data Analyst - Banking",
                "company": "MegaBank",
                "location": config.target_city,
                "description": "SQL, Python, compliance reporting. 2-3 years in banking analytics.",
                "posted_at": "2026-08-21T16:20:00Z",
            },
            {
                "source": "indeed",
                "url": "https://indeed.com/jobs/5003",
                "title": "Business Intelligence Analyst",
                "company": "EcommercePro",
                "location": config.target_city,
                "description": "Tableau dashboards, SQL queries, Python for automation.",
                "posted_at": "2026-08-22T07:45:00Z",
            },
            {
                "source": "indeed",
                "url": "https://indeed.com/jobs/5004",
                "title": "Data Analyst - Product",
                "company": "SaaSCorp",
                "location": config.target_city,
                "description": "SQL, Python, A/B testing. Work with our product team.",
                "posted_at": "2026-08-21T13:00:00Z",
            },
            {
                "source": "naukri",
                "url": "https://naukri.com/jobs/2003",
                "title": "Statistical Analyst",
                "company": "ConsultingFirm",
                "location": config.target_city,
                "description": "Python, R, statistical modeling. 4+ years required.",
                "posted_at": "2026-08-20T15:30:00Z",
            },
            {
                "source": "internshala",
                "url": "https://internshala.com/jobs/3002",
                "title": "Data Analytics Trainee",
                "company": "TrainingAcademy",
                "location": config.target_city,
                "description": "Learn SQL, Excel, Tableau. Certificate upon completion.",
                "posted_at": "2026-08-19T12:00:00Z",
            },
        ]

        all_listings = stable_listings + unique_listings
        new_count = storage.upsert_listings(config.db_path, all_listings)

        return AgentResult(
            agent=MockFetcher.name,
            status="ok",
            records_touched=len(all_listings),
            notes=f"Fetched 12 listings ({new_count} new, {len(all_listings) - new_count} deduped)",
        )
