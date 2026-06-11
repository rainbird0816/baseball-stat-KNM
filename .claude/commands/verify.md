---
description: DB 재빌드 + 스키마 테스트 실행 후 결과 요약
---
다음을 순서대로 실행하고 통과/실패를 한 줄로 요약해줘. 실패 시 원인 위치만 알려줘.

```bash
python scripts/init_db.py --fresh && python -m backend.tests.test_schema
```
