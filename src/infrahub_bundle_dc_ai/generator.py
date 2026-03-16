from __future__ import annotations

import hashlib


class GeneratorMixin:
    def calculate_checksum(self) -> str:
        """Calculates a checksum of the generator based on the related ids during the session"""

        related_ids = self.client.group_context.related_group_ids + self.client.group_context.related_node_ids
        sorted_ids = sorted(related_ids)
        joined = ",".join(sorted_ids)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()
