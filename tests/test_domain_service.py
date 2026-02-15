"""Tests for domain verification and management service."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Domain
from app.services.domain_service import (
    build_dns_records,
    delete_domain,
    get_domain,
    initiate_verification,
    is_domain_verified,
    list_domains,
    refresh_status,
)
from app.services.ses_client import SESError


async def _create_domain(
    db: AsyncSession,
    domain_name: str | None = None,
    verification_status: str = "Pending",
    dkim_status: str = "Pending",
) -> Domain:
    """Helper to create a test domain."""
    name = domain_name or f"{uuid4().hex[:8]}.example.com"
    domain = Domain(
        id=uuid4(),
        domain=name,
        verification_status=verification_status,
        dkim_status=dkim_status,
        verification_token="test-verification-token",
        dkim_tokens=["dkim1", "dkim2", "dkim3"],
    )
    db.add(domain)
    await db.flush()
    return domain


class TestInitiateVerification:
    @patch("app.services.domain_service.ses_client")
    async def test_new_domain(self, mock_ses, db: AsyncSession):
        mock_ses.verify_domain = AsyncMock(return_value="new-token")
        mock_ses.verify_domain_dkim = AsyncMock(return_value=["t1", "t2", "t3"])

        domain_name = f"{uuid4().hex[:8]}.example.com"
        result = await initiate_verification(db, domain_name)

        assert result.domain == domain_name
        assert result.verification_token == "new-token"
        assert result.dkim_tokens == ["t1", "t2", "t3"]
        assert result.verification_status == "Pending"

    @patch("app.services.domain_service.ses_client")
    async def test_existing_domain_re_initiates(self, mock_ses, db: AsyncSession):
        existing = await _create_domain(db)
        mock_ses.verify_domain = AsyncMock(return_value="refreshed-token")
        mock_ses.verify_domain_dkim = AsyncMock(return_value=["r1", "r2", "r3"])

        result = await initiate_verification(db, existing.domain)

        assert result.id == existing.id  # Same record updated
        assert result.verification_token == "refreshed-token"
        assert result.dkim_tokens == ["r1", "r2", "r3"]
        assert result.verification_status == "Pending"

    @patch("app.services.domain_service.ses_client")
    async def test_normalizes_domain_name(self, mock_ses, db: AsyncSession):
        mock_ses.verify_domain = AsyncMock(return_value="token")
        mock_ses.verify_domain_dkim = AsyncMock(return_value=["t1", "t2", "t3"])

        domain_name = f"  {uuid4().hex[:8]}.EXAMPLE.COM  "
        result = await initiate_verification(db, domain_name)

        assert result.domain == domain_name.strip().lower()


class TestBuildDnsRecords:
    async def test_builds_txt_and_cname_records(self, db: AsyncSession):
        domain = await _create_domain(db)
        records = build_dns_records(domain)

        # 1 TXT + 3 CNAMEs = 4 records
        assert len(records) == 4

        txt_records = [r for r in records if r.type == "TXT"]
        assert len(txt_records) == 1
        assert txt_records[0].name == f"_amazonses.{domain.domain}"
        assert txt_records[0].value == domain.verification_token

        cname_records = [r for r in records if r.type == "CNAME"]
        assert len(cname_records) == 3
        for i, cname in enumerate(cname_records):
            token = domain.dkim_tokens[i]
            assert cname.name == f"{token}._domainkey.{domain.domain}"
            assert cname.value == f"{token}.dkim.amazonses.com"


class TestRefreshStatus:
    @patch("app.services.domain_service.ses_client")
    async def test_updates_to_success(self, mock_ses, db: AsyncSession):
        domain = await _create_domain(db)
        mock_ses.get_domain_verification_status = AsyncMock(
            return_value={"VerificationStatus": "Success"}
        )
        mock_ses.get_domain_dkim_status = AsyncMock(
            return_value={"DkimVerified": True}
        )

        result = await refresh_status(db, domain.domain)

        assert result.verification_status == "Success"
        assert result.dkim_status == "Success"
        assert result.verified_at is not None

    @patch("app.services.domain_service.ses_client")
    async def test_pending_status(self, mock_ses, db: AsyncSession):
        domain = await _create_domain(db)
        mock_ses.get_domain_verification_status = AsyncMock(
            return_value={"VerificationStatus": "Pending"}
        )
        mock_ses.get_domain_dkim_status = AsyncMock(
            return_value={"DkimVerified": False}
        )

        result = await refresh_status(db, domain.domain)

        assert result.verification_status == "Pending"
        assert result.dkim_status == "Pending"
        assert result.verified_at is None

    @patch("app.services.domain_service.ses_client")
    async def test_not_found_returns_none(self, mock_ses, db: AsyncSession):
        result = await refresh_status(db, "nonexistent.example.com")
        assert result is None

    @patch("app.services.domain_service.ses_client")
    async def test_ses_error_returns_domain_unchanged(self, mock_ses, db: AsyncSession):
        domain = await _create_domain(db)
        mock_ses.get_domain_verification_status = AsyncMock(
            side_effect=SESError("SES down")
        )

        result = await refresh_status(db, domain.domain)

        assert result is not None
        assert result.verification_status == "Pending"  # Unchanged


class TestGetDomain:
    async def test_find_domain(self, db: AsyncSession):
        domain = await _create_domain(db)
        found = await get_domain(db, domain.domain)
        assert found is not None
        assert found.id == domain.id

    async def test_case_insensitive(self, db: AsyncSession):
        domain = await _create_domain(db)
        found = await get_domain(db, domain.domain.upper())
        assert found is not None

    async def test_not_found(self, db: AsyncSession):
        found = await get_domain(db, "doesnotexist.example.com")
        assert found is None


class TestListDomains:
    async def test_list_empty(self, db: AsyncSession):
        # Use a fresh query — other tests may have added domains
        domains, total = await list_domains(db)
        assert isinstance(domains, list)
        assert isinstance(total, int)
        assert total >= 0

    async def test_list_includes_added_domain(self, db: AsyncSession):
        domain = await _create_domain(db)
        domains, total = await list_domains(db)
        domain_names = [d.domain for d in domains]
        assert domain.domain in domain_names
        assert total >= 1


class TestDeleteDomain:
    async def test_delete_existing(self, db: AsyncSession):
        domain = await _create_domain(db)
        result = await delete_domain(db, domain.domain)
        assert result is True

        # Verify it's gone
        found = await get_domain(db, domain.domain)
        assert found is None

    async def test_delete_nonexistent(self, db: AsyncSession):
        result = await delete_domain(db, "nonexistent.example.com")
        assert result is False


class TestIsDomainVerified:
    async def test_verified_domain(self, db: AsyncSession):
        domain = await _create_domain(db, verification_status="Success")
        assert await is_domain_verified(db, domain.domain) is True

    async def test_pending_domain(self, db: AsyncSession):
        domain = await _create_domain(db, verification_status="Pending")
        assert await is_domain_verified(db, domain.domain) is False

    async def test_nonexistent_domain(self, db: AsyncSession):
        assert await is_domain_verified(db, "nope.example.com") is False
