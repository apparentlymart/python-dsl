
import plex
from plex import (
    Rep,
    Rep1,
    Range,
    Any,
    AnyBut,
    Eof,
    State,
    Str,
    Opt,
    TEXT,
    IGNORE,
)
from plex.errors import UnrecognizedInput
import dsl.diagnostics as diag


class RawScanner(plex.Scanner):

    def handle_newline(self, text):
        if self.bracket_count == 0:
            self.begin('indent')
            return 'NEWLINE'

    def handle_indentation(self, text):
        current_level = self.indents[-1]
        new_level = len(text)
        if new_level > 0 and text[-1] == "\n":
            # Blank line, so skip.
            self.produce('NEWLINE', "\n")
            return

        if new_level > current_level:
            self.indents.append(new_level)
            indent_change = new_level - current_level
            self.produce('INDENT', indent_change)
        elif new_level < current_level:
            self.outdent_to(new_level)
        self.begin('')

    def handle_comment(self, text):
        if text[-1] == "\n":
            test = text[:-1]

        # just treat comments like a funny sort of newline
        if self.bracket_count == 0:
            self.begin('indent')
            self.produce('NEWLINE', "\n")

    def handle_open_bracket(self, text):
        self.bracket_count = self.bracket_count + 1
        return text

    def handle_close_bracket(self, text):
        if self.bracket_count > self.min_bracket_count:
            self.bracket_count = self.bracket_count - 1
        return text

    def eof(self):
        # If there is inconsistent bracket nesting then we'll just return
        # a bare EOF token and let the parser deal with it.
        if self.bracket_count == 0:
            # Always end on a newline, so we can just assume that all
            # lines have ends in the parser.
            self.produce("NEWLINE", "\n")
            self.outdent_to(0)
        self.produce("EOF")

    def outdent_to(self, new_level):
        while new_level < self.indents[-1]:
            self.indents.pop()
            self.produce('OUTDENT', '')
        if self.indents[-1] != new_level:
            raise IndentationError(self.position())

    digit = Range("09")
    letter = Range("azAZ")
    decimal_or_octal_number = (
        (
            Rep1(digit) + Opt(
                Str(".") + Rep1(digit)
            )
        ) + Opt(
            Str("E") + Any("+-") + Rep1(digit)
        )
    )
    hex_number = (
        # We actually slurp up all letters even though only a-f are valid
        # here, so that "0xfg" will parse as a single token that we can
        # report an explicit error for, rather than parsing as "0xf", "g"
        # that will probably just manifest as an unexpected token.
        Str("0x") + Rep1(Range("09azAZ"))
    )
    binary_number = (
        # Slurp up all decimal digits even though only 0 and 1 are valid
        # here, because otherwise "0b02" gets parsed as "0b0", "2" and
        # that would cause a confusing error at parse time; this way we
        # can fail when the parser tries to make sense of the whole number
        # and thus emit a sensible error message.
        Str("0b") + Rep1(digit)
    )

    string_literal = (
        Str('"') + Rep(
            (Str("\\") + (
                # Not all of these escapes are valid, but we'll handle that
                # at parsing time so we can show a nice error message rather
                # than just a token mismatch.
                Any("abcdefghijklmnopqrstuvwxyz\\\"")
            )) | AnyBut("\\\"")
        ) + Str('"')
    )

    ident = (
        (letter | Str("_")) + Rep(letter | Str("_") | digit)
    )

    punct = (
        Any("|&^=<>*/%~+-:,.") |
        Str("==") |
        Str("!=") |
        Str("<=") |
        Str(">=") |
        Str("<<") |
        Str(">>") |
        Str("+/-")
    )

    lexicon = plex.Lexicon([
        (decimal_or_octal_number | hex_number | binary_number, 'NUMBER'),
        (string_literal, 'STRINGLIT'),
        (ident, 'IDENT'),
        (Any("({["), handle_open_bracket),
        (Any(")}]"), handle_close_bracket),
        ((Str("\n") | Eof), handle_newline),
        (punct, TEXT),
        (Rep1(Str(' ')), IGNORE),
        ((Str("#") + Rep(AnyBut("\n")) + Opt(Str("\n"))), handle_comment),
        State('indent', [
            (Rep(Str(" ")) + Opt(Str("\n")), handle_indentation),
        ]),
    ])

    def __init__(self, stream, name=None, expression_only=False):
        plex.Scanner.__init__(self, self.lexicon, stream=stream, name=name)

        self.seen_one_indent = False
        self.indents = [0]
        if expression_only:
            # For parsing expressions we just pretend there's always
            # one bracket open.
            self.bracket_count = 1
        else:
            self.bracket_count = 0
        self.min_bracket_count = self.bracket_count
        if not expression_only:
            self.begin('indent')


class Token(object):
    def __init__(self, type, value, source_range=None):
        self.type = type
        self.value = value
        self.source_range = source_range

    @property
    def display_name(self):
        token_type = self.type

        if token_type == "NEWLINE":
            return "newline"
        elif token_type == "INDENT":
            return "indent"
        elif token_type == "OUTDENT":
            return "outdent"
        elif token_type == "EOF":
            return "end of file"
        else:
            return token.value

    def __eq__(self, other):
        if type(other) is tuple:
            return (self.type, self.value) == other
        elif type(other) is type(self):
            return (self.type, self.value) == (other.type, other.value)
        else:
            return False

    def __getitem__(self, key):
        # Legacy support for callers expecting plex's raw token tuples
        if key == 0:
            return self.type
        elif key == 1:
            return self.value
        else:
            raise IndexError(key)

    def __repr__(self):
        return '<Token %s %r>' % (self.type, self.value)


class Scanner(object):

    def __init__(self, stream, name=None, expression_only=False):
        self.raw_scanner = RawScanner(stream, name, expression_only)
        self.peeked = None
        self.peeking = False
        # Last token position starts off referring to the beginning of the
        # file, so we'll still get a sensible result if we never read any
        # tokens.
        self.last_token = Token(
            type='BEGIN',
            value=None,
            source_range=SourceRange(
                SourceLocation(
                    filename=name,
                    line=1,
                    column=1,
                ),
                SourceLocation(
                    filename=name,
                    line=1,
                    column=1,
                ),
            )
        )
        self.force_eof = False

    def read(self):
        result = self.peek()
        self.peeked = None
        self.last_token = result
        return result

    def peek(self):
        if self.peeked is None:
            self.peeking = True

            if self.force_eof:
                self.peeked = Token(
                    "EOF", None, self.last_token.source_range,
                )
                return self.peeked

            try:
                raw_peeked = self.raw_scanner.read()
                # Skip Plex's generated "EOF" token (where the type is None)
                # since we have our own explicit EOF token.
                if raw_peeked[0] is None:
                    raw_peeked = self.raw_scanner.read()

                raw_position = self.raw_scanner.position()

                # We compute the end of the token we read by assuming it's
                # all on one line and is the same length as what's in
                # result[1], ignoring the NEWLINE, INDENT and OUTDENT tokens
                # since they don't really have any bounds to report.
                if raw_peeked[0] in ('NEWLINE', 'INDENT', 'OUTDENT'):
                    token_length = 0
                else:
                    token_length = len(raw_peeked[1])

                source_range = SourceRange(
                    SourceLocation(
                        filename=raw_position[0],
                        line=raw_position[1],
                        column=raw_position[2] + 1,
                    ),
                    SourceLocation(
                        filename=raw_position[0],
                        line=raw_position[1],
                        column=raw_position[2] + token_length + 1
                    ),
                )

                self.peeked = Token(
                    type=raw_peeked[0],
                    value=raw_peeked[1],
                    source_range=source_range,
                )
            except UnrecognizedInput, ex:
                raw_position = self.raw_position
                self.peeked = Token(
                    type="ERROR",
                    value=diag.InvalidCharacter(
                        location=SourceLocation(
                            filename=raw_position[0],
                            line=raw_position[1],
                            column=raw_position[2] + 1,
                        )
                    )
                )
                self.force_eof = True
            except IndentationError, ex:
                raw_position = ex.raw_position
                self.peeked = Token(
                    type="ERROR",
                    value=diag.InvalidIndentation(
                        location=SourceLocation(
                            filename=raw_position[0],
                            line=raw_position[1],
                            column=raw_position[2] + 1,
                        )
                    )
                )
                self.force_eof = True
            finally:
                self.peeking = False
        return self.peeked

    @property
    def raw_position(self):
        if not self.peeking:
            self.peek()
        return self.raw_scanner.position()

    @property
    def location(self):
        position = self.raw_position
        return SourceLocation(
            position[0],
            position[1],
            position[2] + 1,
        )

    def begin_range(self):
        return SourceRangeBuilder(self)

    @property
    def next_token_range(self):
        return self.peek().source_range

    @property
    def last_token_range(self):
        return self.last_token.source_range

    def next_is_punct(self, symbol):
        token = self.peek()
        return (token[0] == symbol and token[1] == symbol)

    def next_is_keyword(self, name):
        token = self.peek()
        return (token[0] == "IDENT" and token[1] == name)

    def next_is_newline(self):
        return (self.peek()[0] == "NEWLINE")

    def next_is_indent(self):
        return (self.peek()[0] == "INDENT")

    def next_is_outdent(self):
        return (self.peek()[0] == "OUTDENT")

    def next_is_eof(self):
        return (self.peek()[0] == "EOF")

    def next_is_error(self):
        return (self.peek().type == "ERROR")

    def raise_if_next_is_error(self):
        if self.next_is_error():
            raise self.peek().value

    def require_punct(self, symbol):
        if not self.next_is_punct(symbol):
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("PUNCT", symbol),
                got_token=self.peek(),
            )
        return self.read()

    def require_keyword(self, name):
        if not self.next_is_keyword(name):
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("IDENT", name),
                got_token=self.peek(),
            )
        return self.read()

    def require_indent(self):
        if not self.next_is_indent():
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("INDENT", 4),
                got_token=self.peek(),
            )
        return self.read()

    def require_outdent(self):
        if not self.next_is_outdent():
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("OUTDENT", 4),
                got_token=self.peek(),
            )
        return self.read()

    def require_newline(self):
        if not self.next_is_newline():
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("NEWLINE", "\n"),
                got_token=self.peek(),
            )
        return self.read()

    def require_eof(self):
        if not self.next_is_eof():
            self.raise_if_next_is_error()
            raise diag.UnexpectedToken(
                wanted_token=Token("EOF", None),
                got_token=self.peek(),
            )
        return self.read()


class SourceLocation(object):

    def __init__(self, filename, line, column):
        self.filename = filename
        self.line = line
        self.column = column

    def __eq__(self, other):
        if other is None:
            return False
        if isinstance(other, tuple):
            other = SourceLocation(*other)
        return (
            self.filename == other.filename
            and self.line == other.line
            and self.column == other.column
        )

    def __str__(self):
        return "%s:%r,%r" % (
            self.filename,
            self.line,
            self.column,
        )

    def __repr__(self):
        return "SourceLocation<%s>" % self


class SourceRange(object):

    def __init__(self, start, end):
        self.start = start
        self.end = end

    def __eq__(self, other):
        if other is None:
            return False
        return self.start == other.start and self.end == other.end

    def __str__(self):
        return "%s to %s" % (self.start, self.end)

    def __repr__(self):
        return "SourceRange<%s>" % self


class SourceRangeBuilder(object):

    def __init__(self, scanner):
        self.scanner = scanner
        self.start = scanner.location

    def end(self):
        return SourceRange(
            self.start,
            self.scanner.last_token_range.end,
        )


class IndentationError(Exception):

    def __init__(self, raw_position):
        self.raw_position = raw_position
