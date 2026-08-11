"""Job source crawlers used by :mod:`job_tracker`."""

from .base import BaseCrawler, Job, JobRecord
from .company_sites import CompanySitesCrawler
from .jasoseol import JasoseolCrawler
from .jobkorea import JobKoreaCrawler
from .jobplanet import JobPlanetCrawler
from .jumpit import JumpitCrawler
from .saramin import SaraminAPICrawler, SaraminCrawler
from .wanted import WantedCrawler

__all__ = [
    "BaseCrawler",
    "Job",
    "JobRecord",
    "CompanySitesCrawler",
    "JasoseolCrawler",
    "JobKoreaCrawler",
    "JobPlanetCrawler",
    "JumpitCrawler",
    "SaraminCrawler",
    "SaraminAPICrawler",
    "WantedCrawler",
]
