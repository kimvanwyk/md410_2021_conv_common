from decimal import Decimal, getcontext

import attr
import sqlalchemy as sa

import os

getcontext().prec = 20
TWOPLACES = Decimal(10) ** -2

TABLES = {
    "registree": ("md410_2020_conv", "registree"),
    "club": ("md410_2020_conv", "club"),
    "partner_program": ("md410_2020_conv", "partner_program"),
    "full_reg": ("md410_2020_conv", "full_reg"),
    "partial_reg": ("md410_2020_conv", "partial_reg"),
    "pins": ("md410_2020_conv", "pins"),
    "registree_pair": ("md410_2020_conv", "registree_pair"),
    "payment": ("md410_2020_conv", "payment"),
}


@attr.s
class Registree(object):
    reg_num = attr.ib()
    first_names = attr.ib()
    last_name = attr.ib()
    cell = attr.ib()
    email = attr.ib()
    title = attr.ib(default=None)

    def __attrs_post_init__(self):
        self.titled_first_names = f"{self.title if self.title else " "}{self.first_names.strip()}"
        
@attr.s
class DB(object):
    """ Handle postgres database interaction
    """

    host = attr.ib(default=os.getenv('PGHOST', "localhost"))
    port = attr.ib(default=os.getenv('PGPORT', 5432))
    user = attr.ib(default=os.getenv('PGUSER', "postgres"))
    password = attr.ib(default=os.getenv('PGPASSWORD'))
    dbname = attr.ib(default="postgres")
    debug = attr.ib(default=False)

    def __attrs_post_init__(self):
        self.engine = sa.create_engine(
            f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"
        )
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
                [tr.c.reg_num, tr.c.first_names, tr.c.last_name, tr.c.cell, tr.c.email, tr.c.title],
                tr.c.reg_num.in_(self.reg_nums),
            )
        ).fetchall()
        registrees = []
        for r in res:
            registrees.append(Registree(*r))
        return registrees

    def get_all_registrees(self):
        tr = self.tables["registree"]
        res = self.engine.execute(
            sa.select(
                [tr.c.reg_num, tr.c.first_names, tr.c.last_name, tr.c.cell, tr.c.email]
            )
        ).fetchall()
        registrees = []
        for r in res:
            registrees.append(Registree(*r))
        return registrees

    def set_reg_nums(self, reg_num):
        tp = self.tables["registree_pair"]
        res = self.engine.execute(
            sa.select(
                [tp.c.first_reg_num, tp.c.second_reg_num],
                sa.or_(tp.c.first_reg_num == reg_num, tp.c.second_reg_num == reg_num),
            )
        ).fetchone()
        if res:
            self.reg_nums = [res[0], res[1]]
        else:
            self.reg_nums = [reg_num]

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

        vals = dict(
            (k, getattr(registree, k))
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
                "pdg_breakfast",
                "is_lion",
                "sharks_board",
                "golf",
                "sight_seeing",
                "service_project",
            )
        )
        self.engine.execute(tr.insert(vals))

        if registree.is_lion:
            vals = {"reg_num": registree.reg_num, "club": registree.club}
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

    def pair_registrees(self, first_reg_num, second_reg_num):
        tp = self.tables["registree_pair"]
        self.engine.execute(tp.delete(tp.c.first_reg_num == first_reg_num))

        vals = {"first_reg_num": first_reg_num, "second_reg_num": second_reg_num}
        self.engine.execute(tp.insert(vals))
