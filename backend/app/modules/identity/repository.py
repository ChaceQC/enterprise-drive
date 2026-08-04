from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthSession, Tenant, User
from app.modules.device.models import DeviceSession
from app.modules.identity.models import (
    LdapMembershipClaim,
    LdapMembershipRelation,
    LdapObjectBinding,
    LdapSource,
    LdapSyncConflict,
    LdapSyncRun,
    OidcFlow,
    OidcIdentityLink,
    OidcProvider,
)
from app.modules.org.models import (
    Department,
    DepartmentMember,
    UserGroup,
    UserGroupMember,
)


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        result = await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def get_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        for_update: bool = False,
    ) -> User | None:
        query = select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_public_oidc_providers(self, *, tenant_id: UUID) -> list[OidcProvider]:
        result = await self.session.execute(
            select(OidcProvider)
            .where(OidcProvider.tenant_id == tenant_id, OidcProvider.enabled.is_(True))
            .order_by(OidcProvider.name, OidcProvider.id)
        )
        return list(result.scalars().all())

    async def list_oidc_providers(self, *, tenant_id: UUID) -> list[OidcProvider]:
        result = await self.session.execute(
            select(OidcProvider)
            .where(OidcProvider.tenant_id == tenant_id)
            .order_by(OidcProvider.created_at, OidcProvider.id)
        )
        return list(result.scalars().all())

    async def get_oidc_provider_by_slug(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        enabled_only: bool = False,
    ) -> OidcProvider | None:
        conditions = [
            OidcProvider.tenant_id == tenant_id,
            OidcProvider.slug == slug,
        ]
        if enabled_only:
            conditions.append(OidcProvider.enabled.is_(True))
        result = await self.session.execute(select(OidcProvider).where(*conditions))
        return result.scalar_one_or_none()

    async def get_oidc_provider(
        self,
        *,
        tenant_id: UUID,
        provider_id: UUID,
        for_update: bool = False,
    ) -> OidcProvider | None:
        query = select(OidcProvider).where(
            OidcProvider.tenant_id == tenant_id,
            OidcProvider.id == provider_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_oidc_provider(self, provider: OidcProvider) -> OidcProvider:
        self.session.add(provider)
        await self.session.flush()
        return provider

    async def create_oidc_flow(self, flow: OidcFlow) -> OidcFlow:
        self.session.add(flow)
        await self.session.flush()
        return flow

    async def consume_oidc_flow(
        self,
        *,
        state_hash: str,
        now: datetime,
    ) -> OidcFlow | None:
        result = await self.session.execute(
            update(OidcFlow)
            .where(
                OidcFlow.state_hash == state_hash,
                OidcFlow.consumed_at.is_(None),
                OidcFlow.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(OidcFlow)
        )
        return result.scalar_one_or_none()

    async def get_oidc_link_by_subject(
        self,
        *,
        tenant_id: UUID,
        issuer: str,
        subject: str,
    ) -> OidcIdentityLink | None:
        result = await self.session.execute(
            select(OidcIdentityLink).where(
                OidcIdentityLink.tenant_id == tenant_id,
                OidcIdentityLink.issuer == issuer,
                OidcIdentityLink.subject == subject,
            )
        )
        return result.scalar_one_or_none()

    async def get_oidc_link_for_user_provider(
        self,
        *,
        tenant_id: UUID,
        provider_id: UUID,
        user_id: UUID,
    ) -> OidcIdentityLink | None:
        result = await self.session.execute(
            select(OidcIdentityLink).where(
                OidcIdentityLink.tenant_id == tenant_id,
                OidcIdentityLink.provider_id == provider_id,
                OidcIdentityLink.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_oidc_link(self, link: OidcIdentityLink) -> OidcIdentityLink:
        self.session.add(link)
        await self.session.flush()
        return link

    async def list_oidc_links_for_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[tuple[OidcIdentityLink, OidcProvider]]:
        result = await self.session.execute(
            select(OidcIdentityLink, OidcProvider)
            .join(OidcProvider, OidcProvider.id == OidcIdentityLink.provider_id)
            .where(
                OidcIdentityLink.tenant_id == tenant_id,
                OidcIdentityLink.user_id == user_id,
            )
            .order_by(OidcProvider.name, OidcIdentityLink.id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_owned_oidc_link(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        link_id: UUID,
    ) -> OidcIdentityLink | None:
        result = await self.session.execute(
            select(OidcIdentityLink).where(
                OidcIdentityLink.tenant_id == tenant_id,
                OidcIdentityLink.user_id == user_id,
                OidcIdentityLink.id == link_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_oidc_link(self, link: OidcIdentityLink) -> None:
        await self.session.delete(link)
        await self.session.flush()

    async def list_ldap_sources(self, *, tenant_id: UUID) -> list[LdapSource]:
        result = await self.session.execute(
            select(LdapSource)
            .where(LdapSource.tenant_id == tenant_id)
            .order_by(LdapSource.created_at, LdapSource.id)
        )
        return list(result.scalars().all())

    async def get_ldap_source(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> LdapSource | None:
        query = select(LdapSource).where(
            LdapSource.tenant_id == tenant_id,
            LdapSource.id == source_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ldap_source_by_slug(
        self,
        *,
        tenant_id: UUID,
        slug: str,
    ) -> LdapSource | None:
        result = await self.session.execute(
            select(LdapSource).where(
                LdapSource.tenant_id == tenant_id,
                LdapSource.slug == slug,
            )
        )
        return result.scalar_one_or_none()

    async def create_ldap_source(self, source: LdapSource) -> LdapSource:
        self.session.add(source)
        await self.session.flush()
        return source

    async def create_ldap_run(self, run: LdapSyncRun) -> LdapSyncRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_ldap_run(
        self,
        *,
        run_id: UUID,
        for_update: bool = False,
    ) -> LdapSyncRun | None:
        query = select(LdapSyncRun).where(LdapSyncRun.id == run_id)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ldap_source_version(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> int | None:
        query = select(LdapSource.version).where(
            LdapSource.tenant_id == tenant_id,
            LdapSource.id == source_id,
        )
        if for_update:
            query = query.with_for_update()
        value = await self.session.scalar(query)
        return int(value) if value is not None else None

    async def list_ldap_runs(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID | None,
        limit: int,
    ) -> list[LdapSyncRun]:
        conditions = [LdapSyncRun.tenant_id == tenant_id]
        if source_id is not None:
            conditions.append(LdapSyncRun.source_id == source_id)
        result = await self.session.execute(
            select(LdapSyncRun)
            .where(*conditions)
            .order_by(LdapSyncRun.created_at.desc(), LdapSyncRun.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_ldap_conflict(self, conflict: LdapSyncConflict) -> None:
        self.session.add(conflict)
        await self.session.flush()

    async def list_ldap_conflicts(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> list[LdapSyncConflict]:
        result = await self.session.execute(
            select(LdapSyncConflict)
            .where(
                LdapSyncConflict.tenant_id == tenant_id,
                LdapSyncConflict.run_id == run_id,
            )
            .order_by(LdapSyncConflict.created_at, LdapSyncConflict.id)
        )
        return list(result.scalars().all())

    async def get_ldap_binding(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        object_type: str,
        external_id: str,
        for_update: bool = False,
    ) -> LdapObjectBinding | None:
        query = select(LdapObjectBinding).where(
            LdapObjectBinding.tenant_id == tenant_id,
            LdapObjectBinding.source_id == source_id,
            LdapObjectBinding.object_type == object_type,
            LdapObjectBinding.external_id == external_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_ldap_bindings(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        object_type: str | None = None,
    ) -> list[LdapObjectBinding]:
        conditions = [
            LdapObjectBinding.tenant_id == tenant_id,
            LdapObjectBinding.source_id == source_id,
        ]
        if object_type is not None:
            conditions.append(LdapObjectBinding.object_type == object_type)
        result = await self.session.execute(select(LdapObjectBinding).where(*conditions))
        return list(result.scalars().all())

    async def add_ldap_binding(self, binding: LdapObjectBinding) -> LdapObjectBinding:
        self.session.add(binding)
        await self.session.flush()
        return binding

    async def find_user_by_login(
        self,
        *,
        tenant_id: UUID,
        username: str,
    ) -> User | None:
        result = await self.session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                func.lower(User.username) == username.casefold(),
            )
        )
        return result.scalar_one_or_none()

    async def count_active_super_admins(self, *, tenant_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                User.is_super_admin.is_(True),
            )
        )
        return int(value or 0)

    async def get_department(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        result = await self.session.execute(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.id == department_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_group(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> UserGroup | None:
        result = await self.session.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.id == group_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_department_by_path(
        self,
        *,
        tenant_id: UUID,
        path: str,
    ) -> Department | None:
        result = await self.session.execute(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.path == path,
            )
        )
        return result.scalar_one_or_none()

    async def find_group_by_slug(
        self,
        *,
        tenant_id: UUID,
        slug: str,
    ) -> UserGroup | None:
        result = await self.session.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.slug == slug,
            )
        )
        return result.scalar_one_or_none()

    async def add_local_object(self, value: User | Department | UserGroup) -> None:
        self.session.add(value)
        await self.session.flush()

    async def get_department_member(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
        user_id: UUID,
    ) -> DepartmentMember | None:
        result = await self.session.execute(
            select(DepartmentMember).where(
                DepartmentMember.tenant_id == tenant_id,
                DepartmentMember.department_id == department_id,
                DepartmentMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_group_member(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
    ) -> UserGroupMember | None:
        result = await self.session.execute(
            select(UserGroupMember).where(
                UserGroupMember.tenant_id == tenant_id,
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_department_member(self, member: DepartmentMember) -> None:
        self.session.add(member)
        await self.session.flush()

    async def add_group_member(self, member: UserGroupMember) -> None:
        self.session.add(member)
        await self.session.flush()

    async def get_membership_relation(
        self,
        *,
        tenant_id: UUID,
        relation_type: str,
        container_id: UUID,
        user_id: UUID,
    ) -> LdapMembershipRelation | None:
        result = await self.session.execute(
            select(LdapMembershipRelation).where(
                LdapMembershipRelation.tenant_id == tenant_id,
                LdapMembershipRelation.relation_type == relation_type,
                LdapMembershipRelation.container_id == container_id,
                LdapMembershipRelation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_membership_relation(
        self,
        relation: LdapMembershipRelation,
    ) -> LdapMembershipRelation:
        self.session.add(relation)
        await self.session.flush()
        return relation

    async def get_membership_claim(
        self,
        *,
        source_id: UUID,
        relation_id: UUID,
    ) -> LdapMembershipClaim | None:
        result = await self.session.execute(
            select(LdapMembershipClaim).where(
                LdapMembershipClaim.source_id == source_id,
                LdapMembershipClaim.relation_id == relation_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_membership_claim(self, claim: LdapMembershipClaim) -> None:
        self.session.add(claim)
        await self.session.flush()

    async def list_stale_membership_claims(
        self,
        *,
        source_id: UUID,
        run_id: UUID,
    ) -> list[tuple[LdapMembershipClaim, LdapMembershipRelation]]:
        result = await self.session.execute(
            select(LdapMembershipClaim, LdapMembershipRelation)
            .join(
                LdapMembershipRelation,
                LdapMembershipRelation.id == LdapMembershipClaim.relation_id,
            )
            .where(
                LdapMembershipClaim.source_id == source_id,
                LdapMembershipClaim.last_seen_run_id != run_id,
            )
        )
        return [(row[0], row[1]) for row in result.all()]

    async def count_membership_claims(self, *, relation_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(LdapMembershipClaim)
            .where(LdapMembershipClaim.relation_id == relation_id)
        )
        return int(value or 0)

    async def delete_membership_claim(self, claim: LdapMembershipClaim) -> None:
        await self.session.delete(claim)
        await self.session.flush()

    async def delete_membership_relation(self, relation: LdapMembershipRelation) -> None:
        await self.session.delete(relation)
        await self.session.flush()

    async def delete_core_membership(self, relation: LdapMembershipRelation) -> None:
        if relation.relation_type == "department":
            await self.session.execute(
                delete(DepartmentMember).where(
                    DepartmentMember.tenant_id == relation.tenant_id,
                    DepartmentMember.department_id == relation.container_id,
                    DepartmentMember.user_id == relation.user_id,
                )
            )
        else:
            await self.session.execute(
                delete(UserGroupMember).where(
                    UserGroupMember.tenant_id == relation.tenant_id,
                    UserGroupMember.group_id == relation.container_id,
                    UserGroupMember.user_id == relation.user_id,
                )
            )

    async def bump_tenant_permission_version(self, *, tenant_id: UUID) -> int:
        result = await self.session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(permission_version=Tenant.permission_version + 1)
            .returning(Tenant.permission_version)
        )
        return int(result.scalar_one())

    async def revoke_all_user_sessions(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        await self.session.execute(
            update(DeviceSession)
            .where(
                DeviceSession.tenant_id == tenant_id,
                DeviceSession.user_id == user_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
