<!--
  Thanks for contributing to this project!
  Please, DO NOT DELETE ANY TEXT from this template! (unless instructed).
-->

## Checklist
<!--
  Put an `x` in the boxes that apply. You can also fill these out after
  creating the PR. If you're unsure about any of them, don't hesitate to ask.
  This is simply a reminder of what I'm are going to look for before merging 
  your code. Please see the CONTRIBUTING.md for more information.
-->

### [Code Requirements][coding-guide]
- [ ] There is no commented out code in this PR.
- [ ] The code has been formatted according to Ruff. (`ruff check .`)
- [ ] The code passes code quality checks of mypy. (`mypy .`)
- [ ] The code passes spelling checks of codespell. (`codespell .`)

### [Architecture][architecture-guide] for new BMS types
- [ ] The `BMSSample` structure is being filled with all available BMS data.
- [ ] BMS frames are checked for validity, e.g. CRC, length, allowed type.
- [ ] A recorded BLE advertisement has been added for testing.
- [ ] The code does not require persistent values.

### Testing
- [ ] Local tests pass and coverage is 100% branch.
- [ ] Tests have been added to verify that the new code works.
- [ ] Tests use recorded data from the BMS, i.e. test data shall not be generated.

### Contributing
- [ ] Especially, for new BMSs, feel free to add your nickname to the `authors` list in `pyproject.toml`
- [ ] I agree that the [project license][LICENSE] is used for my contribution

[contribution-guide]: https://github.com/patman15/aiobmsble/tree/main?tab=contributing-ov-file
[coding-guide]: https://github.com/patman15/aiobmsble/tree/main?tab=contributing-ov-file#coding-style-guidelines
[architecture-guide]: https://github.com/patman15/aiobmsble/tree/main?tab=contributing-ov-file#architecture-guidelines
[BMS-type]: https://github.com/patman15/aiobmsble/tree/main?tab=contributing-ov-file#how-to-qualify-as-a-bms
[LICENSE]: https://github.com/patman15/aiobmsble/blob/main/LICENSE
