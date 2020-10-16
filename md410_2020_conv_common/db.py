from collections import defaultdict
from datetime import datetime
from decimal import Decimal, getcontext


import attr
import sqlalchemy as sa

import os

getcontext().prec = 20
TWOPLACES = Decimal(10) ** -2

TABLES = {
    "registree": ("md410_2021_conv", "registree"),
    "club": ("md410_2021_conv", "club"),
    "partner_program": ("md410_2021_conv", "partner_program"),
    "full_reg": ("md410_2021_conv", "full_reg"),
    "partial_reg": ("md410_2021_conv", "partial_reg"),
    "pins": ("md410_2021_conv", "pins"),
    "registree_pair": ("md410_2021_conv", "registree_pair"),
    "payment": ("md410_2021_conv", "payment"),
    "2020_registree": ("md410_2020_conv", "registree"),
    "2020_registree_pair": ("md410_2020_conv", "registree_pair"),
    "2020_payment": ("md410_2020_conv", "payment"),
}

COSTS = {
    "full_regs": 1285,
    "banquets": 500,
    "conventions": 400,
    "themes": 450,
    "pins": 55,
}


@attr.s
class Registree(object):
    reg_num = attr.ib()
    first_names = attr.ib()
    last_name = attr.ib()
    cell = attr.ib()
    email = attr.ib()
    is_lion = attr.ib()
    club = attr.ib(default=None)
    title = attr.ib(default=None)
    full_regs = attr.ib(default=0)
    banquets = attr.ib(default=0)
    conventions = attr.ib(default=0)
    themes = attr.ib(default=0)
    pins = attr.ib(default=0)
    payments = attr.ib(default=0)
    titled_first_names = attr.ib(init=False)
    paid_in_full = attr.ib(init=False)

    def __attrs_post_init__(self):
        t = f"{self.title} " if self.title else ""
        self.titled_first_names = f"{t}{self.first_names.strip()}"
        owed = sum(v * getattr(self, k, 0) for (k, v) in COSTS.items())
        self.paid_in_full = self.payments >= owed


@attr.s
class DB(object):
    """ Handle postgres database interaction
    """

    host = attr.ib(default=os.getenv("PGHOST", "localhost"))
    port = attr.ib(default=os.getenv("PGPORT", 5432))
    user = attr.ib(default=os.getenv("PGUSER", "postgres"))
    password = attr.ib(default=os.getenv("PGPASSWORD"))
    dbname = attr.ib(default="postgres")
    debug = attr.ib(default=False)

    def __attrs_post_init__(self):
        self.engine = sa.create_engine(f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}", echo=self.debug,)
        md = sa.MetaData()
        md.bind = self.engine
        self.engine.autocommit = True
        self.tables = {}
        for (k, (schema, name)) in TABLES.items():
            self.tables[k] = sa.Table(name, md, autoload=True, schema=schema)
        self.reg_nums = []

    def get_registrees(self, reg_num):
        self.set_reg_nums(reg_num)
        tr = self.tables["registree"]
        res = self.engine.execute(
            sa.select(
                [tr.c.reg_num, tr.c.first_names, tr.c.last_name, tr.c.cell, tr.c.email, tr.c.title,],
                whereclause=sa.and_(tr.c.reg_num.in_(self.reg_nums), tr.c.cancellation_timestamp == None),
            )
        ).fetchall()
        registrees = []
        for r in res:
            registrees.append(Registree(*r))
        return registrees

    def get_all_registrees(self, reg_nums=None):
        tr = self.tables["registree"]
        tfr = self.tables["full_reg"]
        tpr = self.tables["partial_reg"]
        tpi = self.tables["pins"]
        tpy = self.tables["payment"]
        tc = self.tables["club"]

        query = sa.select([tr.c.reg_num, tr.c.first_names, tr.c.last_name, tr.c.cell, tr.c.email, tr.c.is_lion,])

        if reg_nums:
            query = query.where(sa.and_(tr.c.reg_num.in_(reg_nums), tr.c.cancellation_timestamp == None))
        else:
            query = query.where(tr.c.cancellation_timestamp == None)
        res = self.engine.execute(query).fetchall()
        registrees = []
        for r in res:
            d = dict(r)
            if r.is_lion:
                try:
                    d["club"] = self.engine.execute(tc.select(whereclause=tc.c.reg_num == d["reg_num"])).fetchone()[1]
                except Exception:
                    pass
            try:
                d["full_regs"] = self.engine.execute(tfr.select(whereclause=tfr.c.reg_num == d["reg_num"])).fetchone()[1]
            except Exception:
                pass
            try:
                partial = self.engine.execute(tpr.select(whereclause=tpr.c.reg_num == d["reg_num"])).fetchone()
                d["banquets"] = partial["banquet_quantity"]
                d["conventions"] = partial["convention_quantity"]
                d["themes"] = partial["theme_quantity"]
            except Exception:
                pass

            try:
                d["pins"] = self.engine.execute(tpi.select(whereclause=tpi.c.reg_num == d["reg_num"])).fetchone()[1]
            except Exception:
                pass

            try:
                d["payments"] = sum(p.amount for p in self.engine.execute(tpy.select(whereclause=tpy.c.reg_num == d["reg_num"])).fetchall())
            except Exception:
                pass
            registrees.append(Registree(**d))
        return registrees

    def set_reg_nums(self, reg_num):
        tp = self.tables["registree_pair"]
        res = self.engine.execute(
            sa.select([tp.c.first_reg_num, tp.c.second_reg_num], sa.or_(tp.c.first_reg_num == reg_num, tp.c.second_reg_num == reg_num),)
        ).fetchone()
        self.reg_nums = [res[0], res[1]] if res else [reg_num]

    def record_payment(self, amount, timestamp):
        tp = self.tables["payment"]
        amt = Decimal(amount).quantize(TWOPLACES) / (len(self.reg_nums))
        for rn in self.reg_nums:
            d = {"timestamp": timestamp, "reg_num": rn, "amount": amt}
            res = self.engine.execute(tp.insert(d))

    def upload_registree(self, registree):
        tr = self.tables["registree"]
        tc = self.tables["club"]
        tpp = self.tables["partner_program"]
        tfr = self.tables["full_reg"]
        tpr = self.tables["partial_reg"]
        tp = self.tables["pins"]
        for t in (tr, tc, tpp, tfr, tpr, tp):
            self.engine.execute(t.delete(t.c.reg_num == registree.reg_num))

        vals = {
            k: getattr(registree, k)
            for k in (
                "reg_num",
                "timestamp",
                "first_names",
                "last_name",
                "cell",
                "email",
                "dietary",
                "disability",
                "name_badge",
                "first_mdc",
                "mjf_lunch",
                # "pdg_breakfast",
                "is_lion",
                # "sharks_board",
                # "golf",
                # "sight_seeing",
                # "service_project",
            )
        }
        self.engine.execute(tr.insert(vals))

        if registree.is_lion:
            vals = {"reg_num": registree.reg_num, "club": registree.club, "district": registree.district}
            self.engine.execute(tc.insert(vals))
        else:
            vals = {"reg_num": registree.reg_num, "quantity": 1}
            self.engine.execute(tpp.insert(vals))

        if registree.full_reg:
            vals = {"reg_num": registree.reg_num, "quantity": registree.full_reg}
            self.engine.execute(tfr.insert(vals))

        if registree.partial_reg:
            vals = {
                "reg_num": registree.reg_num,
                "banquet_quantity": registree.partial_reg.banquet,
                "convention_quantity": registree.partial_reg.convention,
                "theme_quantity": registree.partial_reg.theme,
            }
            self.engine.execute(tpr.insert(vals))

        if registree.pins:
            vals = {"reg_num": registree.reg_num, "quantity": registree.pins}
            self.engine.execute(tp.insert(vals))

    def cancel_registration(self, reg_nums):
        tr = self.tables["registree"]
        trp = self.tables["registree_pair"]
        tc = self.tables["club"]
        tpp = self.tables["partner_program"]
        tfr = self.tables["full_reg"]
        tpr = self.tables["partial_reg"]
        tp = self.tables["pins"]
        for t in (tc, tfr, tpp, tpr, tp):
            self.engine.execute(t.delete(t.c.reg_num.in_(reg_nums)))
        self.engine.execute(trp.delete(trp.c.first_reg_num.in_(reg_nums)))

        dt = datetime.now()
        self.engine.execute(tr.update(tr.c.reg_num.in_(reg_nums), {"cancellation_timestamp": dt}))

    def pair_registrees(self, first_reg_num, second_reg_num):
        tp = self.tables["registree_pair"]
        self.engine.execute(tp.delete(tp.c.first_reg_num == first_reg_num))

        vals = {"first_reg_num": first_reg_num, "second_reg_num": second_reg_num}
        self.engine.execute(tp.insert(vals))

    def get_2020_payees(self):
        tr = self.tables["2020_registree"]
        trp = self.tables["2020_registree_pair"]
        tp = self.tables["2020_payment"]

        res = self.engine.execute(
            sa.select(
                [tr.c.reg_num, tr.c.first_names, tr.c.last_name, tp.c.amount, tr.c.cancellation_timestamp],
                sa.and_(tr.c.reg_num == tp.c.reg_num, tr.c.cancellation_timestamp == None),
            ).order_by(tr.c.reg_num)
        ).fetchall()
        totals = defaultdict(float)
        names = {}
        for r in res:
            totals[r.reg_num] += r.amount
            names[r.reg_num] = f"{r.last_name}, {r.first_names}"

        return {r: (name, totals[r]) for (r, name) in names.items()}
