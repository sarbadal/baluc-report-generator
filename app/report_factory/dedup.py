from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DedupParameters:
    date: pd.Timestamp
    caption: str
    ppl: str
    state: str
    publication: str


TM2_OFFSETS = {"Tm1": -1, "T": -2, "Tp1": -3, "Tp2": -4}
TM1_OFFSETS = {"T": -1, "Tp1": -2}
TP1_OFFSETS = {"T": 1}
TP2_OFFSETS = {"Tm1": 3, "T": 2, "Tp1": 1}


def calculate_window_sum(df: pd.DataFrame, parameters: DedupParameters, window_offsets: dict[str, int]) -> int:
    """
    Calculate the sum of values in the specified window for the given parameters.

    Args:
        df (pd.DataFrame): The DataFrame containing the data.
        parameters (DedupParameters): The parameters for the current row.
        window_offsets (dict[str, int]): A dictionary mapping target columns to their offsets.

    Returns:
        int: The sum of values in the specified window.
    """
    collected = []
    for target, offset in window_offsets.items():
        target_date = parameters.date + pd.Timedelta(days=offset)
        matching_rows = df[
            (df["date"] == target_date)
            & (df["state"] == parameters.state)
        ]
        collected.append(matching_rows[target].sum())
    return sum(collected)


class Deduplicator:
    def __init__(
        self,
        df: pd.DataFrame,
        tm2_offset: dict[str, int] | None = None,
        tm1_offset: dict[str, int] | None = None,
        tp1_offset: dict[str, int] | None = None,
        tp2_offset: dict[str, int] | None = None,
        tm2: str = "Tm2",
        tm1: str = "Tm1",
        tp1: str = "Tp1",
        tp2: str = "Tp2",
        window_sum_calculator: Callable = calculate_window_sum,
    ) -> None:
        """Init the Deduplicator with the given parameters."""
        self.df = df.copy()
        self.df["date"] = pd.to_datetime(self.df["date"], errors="raise")
        if self.df["date"].isna().any():
            raise ValueError("Deduplicator requires a valid date for every row.")
        tm2_offset = TM2_OFFSETS if tm2_offset is None else tm2_offset
        tm1_offset = TM1_OFFSETS if tm1_offset is None else tm1_offset
        tp1_offset = TP1_OFFSETS if tp1_offset is None else tp1_offset
        tp2_offset = TP2_OFFSETS if tp2_offset is None else tp2_offset
        metric_columns = dict.fromkeys(
            [*tm2_offset, *tm1_offset, *tp1_offset, *tp2_offset]
        )
        for column in metric_columns:
            values = self.df[column].replace(r"^\s*$", pd.NA, regex=True)
            self.df[column] = pd.to_numeric(values, errors="raise")
        self.tm2_offset = tm2_offset
        self.tm1_offset = tm1_offset
        self.tp1_offset = tp1_offset
        self.tp2_offset = tp2_offset
        self.tm2 = tm2
        self.tm1 = tm1
        self.tp1 = tp1
        self.tp2 = tp2
        self.window_sum_calculator = window_sum_calculator

    def _parameters_from_row(self, row: pd.Series) -> DedupParameters:
        return DedupParameters(
            date=row["date"],
            caption=row["caption"],
            ppl=row["ppl"],
            state=row["state"],
            publication=row["pub_name"],
        )

    def _calculate_window_sum(self, parameters: DedupParameters, window_offsets: dict[str, int]) -> int:
        return self.window_sum_calculator(self.df, parameters, window_offsets)

    def calculate_tm2(self, parameters: DedupParameters) -> int:
        return self._calculate_window_sum(parameters, self.tm2_offset)

    def calculate_tm1(self, parameters: DedupParameters) -> int:
        return self._calculate_window_sum(parameters, self.tm1_offset)

    def calculate_tp1(self, parameters: DedupParameters) -> int:
        return self._calculate_window_sum(parameters, self.tp1_offset)

    def calculate_tp2(self, parameters: DedupParameters) -> int:
        return self._calculate_window_sum(parameters, self.tp2_offset)

    def _add_column(self, column_name: str, calculator: Callable[[DedupParameters], int]) -> "Deduplicator":
        self.df[column_name] = self.df.apply(
            lambda row: calculator(self._parameters_from_row(row)),
            axis=1,
        )
        return self

    def add_tm2_column(self) -> "Deduplicator":
        return self._add_column("_Tm2", self.calculate_tm2)

    def add_tm1_column(self) -> "Deduplicator":
        return self._add_column("_Tm1", self.calculate_tm1)

    def add_tp1_column(self) -> "Deduplicator":
        return self._add_column("_Tp1", self.calculate_tp1)

    def add_tp2_column(self) -> "Deduplicator":
        return self._add_column("_Tp2", self.calculate_tp2)

    def add_all_columns(self) -> "Deduplicator":
        for add_column in (
            self.add_tm2_column,
            self.add_tm1_column,
            self.add_tp1_column,
            self.add_tp2_column,
        ):
            add_column()
        return self

    def _deduplicate(
        self,
        auxiliary_column: str,
        target_column: str,
        calculator: Callable[[DedupParameters], int],
    ) -> "Deduplicator":
        if auxiliary_column not in self.df.columns:
            self._add_column(auxiliary_column, calculator)
        self.df.loc[self.df[auxiliary_column] > 0, target_column] = 0
        return self

    def deduplicate_tm2(self) -> "Deduplicator":
        return self._deduplicate("_Tm2", self.tm2, self.calculate_tm2)

    def deduplicate_tm1(self) -> "Deduplicator":
        return self._deduplicate("_Tm1", self.tm1, self.calculate_tm1)

    def deduplicate_tp1(self) -> "Deduplicator":
        return self._deduplicate("_Tp1", self.tp1, self.calculate_tp1)

    def deduplicate_tp2(self) -> "Deduplicator":
        return self._deduplicate("_Tp2", self.tp2, self.calculate_tp2)

    def deduplicate_all(self) -> "Deduplicator":
        for deduplicate in (
            self.deduplicate_tm2,
            self.deduplicate_tm1,
            self.deduplicate_tp1,
            self.deduplicate_tp2,
        ):
            deduplicate()
        return self

    def drop_auxiliary_columns(self) -> "Deduplicator":
        self.df = self.df.drop(columns=["_Tm2", "_Tm1", "_Tp1", "_Tp2"])
        return self
