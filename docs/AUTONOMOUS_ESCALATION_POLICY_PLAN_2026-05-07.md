# Autonomous Escalation Policy Plan

Date: 2026-05-07

This note records follow-on work required before any operator turns on autonomous sending for brain-path drafts.

## Why This Exists

2026-05-07 closed the brain-path adversarial-review asymmetry by inserting legacy-style draft review before persistence. That makes autonomous mode possible to reason about, but it does not define the final auto-send gate.

Autonomous mode must evaluate brain output, adversarial review output, and legacy policy output together through one explicit decision function.

## Required Decision Function

Create a single `should_auto_send(...)` style decision surface that evaluates at least:

- reviewer verdict
- brain `auto_send_allowed`
- brain `escalation_required`
- brain confidence threshold
- legacy `policy_result.block_send`
- hard-stop policy warnings
- missing property identification / knowledge-gap conditions

## Current Working Criteria

Auto-send only if all of these are true:

- adversarial reviewer verdict is `approve` or `revise`
- brain `auto_send_allowed == True`
- brain `escalation_required == False`
- confidence is at or above an operator-configurable threshold
- legacy `policy_result.block_send == False`
- no hard-stop policy warnings are present

Otherwise hold for operator review.

## Reviewer Verdict Mapping

- `approve` -> auto-send may proceed
- `revise` -> auto-send may proceed using the revised text
- `human_review` -> do not auto-send
- `block` -> do not auto-send

## Implementation Requirements

- operator-level configuration for confidence threshold
- operator-level configuration for which warning classes are hard-stops
- structured observability showing why a draft would or would not auto-send
- synthetic tests covering reviewer verdicts, policy stops, confidence stops, and missing-context stops
- confirmation that `send_inquiry_on_timeout` fires reliably after
  worker-tier restoration before autonomous mode is considered
  supported for any operator using timeout-based automation paths

## Status

Not implemented.

This is a hard prerequisite for any operator enabling autonomous mode on pre-booking brain drafts.
