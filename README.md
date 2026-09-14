# Read100

Read100 5–9세 문해력 학습 서비스의 GitHub Source of Truth입니다.

- Baseline: Read100 v1.5
- Evidence Learning Engine 포함
- Source preservation: PASS (35/35 identical; runtime/secret files excluded or sanitized)
- Baseline integrity CI: PASS
- Runtime environments: deployment targets only
- FounderOps: 별도 orchestration repository
- Production deployment workflow: not enabled

## Release rule
GitHub source → automated integrity/regression gate → human acceptance → separately approved deployment/promotion.

기존 runtime과 FounderOps는 이 baseline migration 과정에서 변경하지 않았습니다.
