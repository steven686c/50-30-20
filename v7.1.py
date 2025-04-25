"""
Presupuesto 50-20-30 · v7.1
────────────────────────────────────────────────────────────────────────
• Multi-usuario y perfiles  
• Cuentas / certificados / inversiones (saldo + % interés)  
• Tarjetas de crédito (límite, corte, pago, % cash-back) + alerta 5 días antes  
• Gestor de deudas (saldo, tasa, pago mínimo)  
• Ingresos y gastos con selección de fuente y actualización de saldos  
• Metas (objetivo, fecha límite, ahorro/mes necesario) – compat. legacy  
• Visualizaciones: pie 50-20-30 · barras por categoría · línea evolución mensual  
• Forecast 12 meses (cash-flow medio)  
• Eliminación de ingresos/gastos vía multiselect (sin errores)  
────────────────────────────────────────────────────────────────────────
Requisitos:
    pip install streamlit pandas matplotlib python-dateutil
Ejecutar:
    streamlit run Presupuesto.py
"""

from __future__ import annotations
import os, json, hashlib, datetime as dt
from dataclasses import dataclass, asdict, field
from typing import List, Dict

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from dateutil.relativedelta import relativedelta

# ─ utilidades ──────────────────────────────────────────────────────
DATA_DIR = "presupuesto_data"
os.makedirs(DATA_DIR, exist_ok=True)
TODAY   = dt.date.today()
_hash   = lambda s: hashlib.sha256(s.encode()).hexdigest()
_rerun  = lambda: (st.rerun() if hasattr(st, "rerun") else st.experimental_rerun())
_ym     = lambda iso: (dt.date.fromisoformat(iso).year,
                       dt.date.fromisoformat(iso).month)
first_m = lambda y, m: dt.date(y, m, 1)
_san    = lambda s: "".join(c if c.isalnum() else "_" for c in s)

# ─ autenticación ─────────────────────────────────────────────────
USERS_FILE = os.path.join(DATA_DIR, "users.json")
load_users = lambda: json.load(open(USERS_FILE, "r", encoding="utf-8")) \
                    if os.path.exists(USERS_FILE) else {}
save_users = lambda d: json.dump(d, open(USERS_FILE, "w", encoding="utf-8"), indent=2)
def register_user(u: str, p: str):
    users = load_users(); users[u] = {"pw": _hash(p)}; save_users(users)
def authenticate(u: str, p: str) -> bool:
    users = load_users(); return u in users and users[u]["pw"] == _hash(p)

# ─ modelos de datos ────────────────────────────────────────────────
@dataclass
class Account:
    name   : str
    type   : str
    balance: float = 0.0
    rate   : float = 0.0

@dataclass
class CreditCard:
    name     : str
    limit    : float
    cut_day  : int
    pay_day  : int
    balance  : float = 0.0
    cashback : float = 0.0

@dataclass
class Debt:
    name       : str
    balance    : float
    rate       : float
    min_payment: float

@dataclass
class Transaction:
    date    : str
    amount  : float
    category: str
    subcat  : str
    source  : str
    recurrent: bool = False

@dataclass
class Goal:
    name    : str
    target  : float
    deadline: str
    saved   : float = 0.0
    def months_left(self) -> int:
        return max((dt.date.fromisoformat(self.deadline) - TODAY).days // 30, 1)
    def need_pm(self) -> float:
        return max(self.target - self.saved, 0) / self.months_left()

@dataclass
class Budget:
    accounts : List[Account]     = field(default_factory=lambda:[Account("Cuenta Nómina","Débito")])
    cards    : List[CreditCard]  = field(default_factory=lambda:[CreditCard("Banreservas",0.0,15,5)])
    debts    : List[Debt]        = field(default_factory=list)
    incomes  : List[Transaction] = field(default_factory=list)
    expenses : List[Transaction] = field(default_factory=list)
    goals    : List[Goal]        = field(default_factory=list)
    def _tot(self, seq, y, m): return sum(t.amount for t in seq if _ym(t.date)==(y, m))
    def cashflow_m(self, y, m): return self._tot(self.incomes, y, m) - self._tot(self.expenses, y, m)

# ─ persistencia ───────────────────────────────────────────────────
_f = lambda u, p: os.path.join(DATA_DIR, f"{_hash(u)}__{_hash(p)}.json")
def _tx_clean(d: Dict) -> Dict:
    if "account" in d and "source" not in d:
        d["source"] = d.pop("account")
    return {k: v for k, v in d.items() if k in Transaction.__annotations__}
def _goal_clean(d: Dict) -> Dict:
    g = {k: v for k, v in d.items() if k in Goal.__annotations__}
    g.setdefault("target", 0.0)
    g.setdefault("deadline", (TODAY + relativedelta(years=1)).isoformat())
    g.setdefault("saved", 0.0)
    g.setdefault("name", f"Meta {len(g)}")
    return g

def load_budget(u: str, p: str) -> Budget:
    if not os.path.exists(_f(u, p)):
        return Budget()
    d = json.load(open(_f(u, p), "r", encoding="utf-8"))
    return Budget(
        accounts =[Account(**a) for a in d.get("accounts", [])],
        cards    =[CreditCard(**c) for c in d.get("cards",    [])],
        debts    =[Debt(**v)       for v in d.get("debts",    [])],
        incomes  =[Transaction(**_tx_clean(t)) for t in d.get("incomes",  [])],
        expenses =[Transaction(**_tx_clean(t)) for t in d.get("expenses", [])],
        goals    =[Goal(**_goal_clean(g))      for g in d.get("goals",    [])],
    )
def save_budget(u: str, p: str, b: Budget):
    json.dump(asdict(b), open(_f(u, p), "w", encoding="utf-8"), indent=2)

# ─ gráficos ───────────────────────────────────────────────────────
def pie50(df):
    fig, ax = plt.subplots()
    vals = df["Monto"].values; mask = vals > 1e-2
    if vals[mask].sum() == 0:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center")
    else:
        ax.pie(vals[mask], labels=df.index[mask], autopct=lambda p: f"{p:.1f}%", startangle=90)
    ax.axis("equal"); return fig

def bar_spend(df):
    fig, ax = plt.subplots()
    df.plot(kind="bar", ax=ax, legend=False)
    ax.set_ylabel("RD$"); return fig

def line_month(df):
    fig, ax = plt.subplots()
    df.plot(ax=ax); ax.set_ylabel("RD$"); ax.set_xlabel("Mes"); return fig

# ─ login / registro ──────────────────────────────────────────────
def login_screen():
    st.title("💰 Presupuesto 50-20-30")
    t1, t2 = st.tabs(["Iniciar sesión", "Registrarse"])
    with t1:
        u = st.text_input("Usuario", key="login_user")
        p = st.text_input("Contraseña", type="password", key="login_pass")
        if st.button("Entrar", key="login_btn") and authenticate(u, p):
            st.session_state.user = u; _rerun()
    with t2:
        nu = st.text_input("Nuevo usuario", key="reg_user")
        np = st.text_input("Contraseña", type="password", key="reg_pass")
        if st.button("Registrar", key="reg_btn") and nu and np:
            if nu in load_users(): st.error("Ese usuario ya existe")
            else: register_user(nu, np); st.success("✅ Usuario creado")

# ─ selección de perfil ────────────────────────────────────────────
def choose_profile(user: str):
    key = f"profiles_{user}"
    st.session_state.setdefault(key, ["Principal"])
    profs = st.session_state[key]
    st.session_state.profile = st.radio("Perfil", profs, horizontal=True, key="pf_radio")
    with st.expander("Gestionar perfiles"):
        np = st.text_input("Nuevo perfil", key="pf_new")
        if st.button("Añadir", key="pf_add") and np and np not in profs:
            profs.append(np); _rerun()
        if len(profs) > 1:
            dp = st.selectbox("Eliminar perfil", profs, key="pf_del_sel")
            if st.button("Borrar", key="pf_del_btn") and dp != st.session_state.profile:
                profs.remove(dp)
                if os.path.exists(_f(user, dp)):
                    os.remove(_f(user, dp))
                _rerun()
    st.divider()

# ─ dashboard ─────────────────────────────────────────────────────
def dashboard():
    user, prof = st.session_state.user, st.session_state.profile
    b = load_budget(user, prof)
    y, m = TODAY.year, TODAY.month

    # Sidebar: configuración
    with st.sidebar:
        st.header("⚙️ Fuentes de dinero")

        # Cuentas / inversiones
        with st.expander("Cuentas / Certificados / Inversiones"):
            for acc in list(b.accounts):
                sid = _san(acc.name)
                acc.name    = st.text_input("Nombre", acc.name, key=f"acc_n_{sid}")
                acc.balance = st.number_input("Saldo", acc.balance, key=f"acc_b_{sid}")
                acc.rate    = st.number_input("% interés/año", acc.rate, key=f"acc_r_{sid}")
                c1, c2 = st.columns(2)
                if c1.button("Guardar", key=f"acc_s_{sid}"):
                    save_budget(user, prof, b); _rerun()
                if c2.button("❌", key=f"acc_d_{sid}"):
                    b.accounts.remove(acc); save_budget(user, prof, b); _rerun()
            st.markdown("---")
            nn = st.text_input("Nueva cuenta", key="acc_new_name")
            nb = st.number_input("Saldo inicial", 0.0, key="acc_new_bal")
            nr = st.number_input("% interés/año", 0.0, key="acc_new_rate")
            nt = st.selectbox("Tipo", ["Débito","Certificado","Inversión"], key="acc_new_type")
            if st.button("Agregar cuenta", key="acc_new_btn") and nn:
                b.accounts.append(Account(nn, nt, nb, nr))
                save_budget(user, prof, b); _rerun()

        # Tarjetas de crédito
        with st.expander("Tarjetas de crédito"):
            for c in list(b.cards):
                sid = _san(c.name)
                c.name  = st.text_input("Nombre", c.name, key=f"cc_n_{sid}")
                c.limit = st.number_input("Límite", c.limit, step=100.0, key=f"cc_l_{sid}")
                default_cut = min(max(c.cut_day,1),31)
                c.cut_day = st.number_input(
                    "Día corte", min_value=1, max_value=31, value=default_cut, step=1, key=f"cc_c_{sid}"
                )
                default_pay = min(max(c.pay_day,1),31)
                c.pay_day = st.number_input(
                    "Día pago", min_value=1, max_value=31, value=default_pay, step=1, key=f"cc_p_{sid}"
                )
                c.cashback = st.number_input("% cashback", c.cashback, key=f"cc_cb_{sid}")
                col1, col2 = st.columns(2)
                if col1.button("Guardar", key=f"cc_s_{sid}"):
                    save_budget(user, prof, b); _rerun()
                if col2.button("❌", key=f"cc_d_{sid}"):
                    b.cards.remove(c); save_budget(user, prof, b); _rerun()
            st.markdown("---")
            nt = st.text_input("Nueva tarjeta", key="cc_new_name")
            if st.button("Añadir tarjeta", key="cc_new_btn") and nt:
                b.cards.append(CreditCard(nt, 0.0, 15, 5))
                save_budget(user, prof, b); _rerun()

        # Deudas
        with st.expander("Deudas"):
            for d in list(b.debts):
                sid = _san(d.name)
                d.name        = st.text_input("Nombre", d.name, key=f"deb_n_{sid}")
                d.balance     = st.number_input("Saldo", d.balance, key=f"deb_b_{sid}")
                d.rate        = st.number_input("% interés", d.rate, key=f"deb_r_{sid}")
                d.min_payment = st.number_input("Pago mínimo", d.min_payment, key=f"deb_m_{sid}")
                c1, c2 = st.columns(2)
                if c1.button("Guardar", key=f"deb_s_{sid}"):
                    save_budget(user, prof, b); _rerun()
                if c2.button("❌", key=f"deb_d_{sid}"):
                    b.debts.remove(d); save_budget(user, prof, b); _rerun()
            st.markdown("---")
            nd = st.text_input("Nueva deuda", key="deb_new_name")
            if st.button("Agregar deuda", key="deb_new_btn") and nd:
                b.debts.append(Debt(nd, 0.0, 0.0, 0.0))
                save_budget(user, prof, b); _rerun()

        # Metas de ahorro
        with st.expander("Metas de ahorro"):
            for g in list(b.goals):
                sid = _san(g.name)
                pct = int(g.saved / g.target * 100) if g.target else 0
                st.progress(pct, text=f"{g.name}: {g.saved:,.0f}/{g.target:,.0f} • falta {g.need_pm():,.0f}/mes")
                add = st.number_input("Aportar", 0.0, key=f"goal_add_{sid}")
                c1, c2 = st.columns(2)
                if c1.button("Sumar", key=f"goal_plus_{sid}") and add:
                    g.saved += add; save_budget(user, prof, b); _rerun()
                if c2.button("❌", key=f"goal_del_{sid}"):
                    b.goals.remove(g); save_budget(user, prof, b); _rerun()
            st.markdown("---")
            with st.form("goal_form"):
                gn = st.text_input("Nombre meta")
                gt = st.number_input("Objetivo", 0.0)
                gd = st.date_input("Fecha límite", TODAY + relativedelta(months=12))
                if st.form_submit_button("Crear meta") and gn:
                    b.goals.append(Goal(gn, gt, gd.isoformat()))
                    save_budget(user, prof, b); _rerun()

        st.divider()

        # Formulario ingreso
        with st.form("inc_form"):
            st.subheader("➕ Ingreso")
            idt = st.date_input("Fecha", TODAY, key="inc_date")
            iam = st.number_input("Monto", 0.0, key="inc_amt")
            icat= st.text_input("Categoría", "Salario", key="inc_cat")
            isub= st.text_input("Sub-cat", "General", key="inc_sub")
            src = st.selectbox("Cuenta destino", [a.name for a in b.accounts] + [c.name for c in b.cards], key="inc_src")
            irec= st.checkbox("Recurrente", key="inc_rec")
            if st.form_submit_button("Guardar ingreso"):
                for a in b.accounts:
                    if a.name == src: a.balance += iam
                for c in b.cards:
                    if c.name == src: c.balance -= iam
                b.incomes.append(Transaction(idt.isoformat(), iam, icat, isub, src, irec))
                save_budget(user, prof, b); _rerun()

        # Formulario gasto
        with st.form("exp_form"):
            st.subheader("➖ Gasto")
            gdt = st.date_input("Fecha", TODAY, key="exp_date")
            gam = st.number_input("Monto", 0.0, key="exp_amt")
            gcat= st.selectbox("Categoría", ["Needs","Wants","Savings","Deuda","Pago tarjeta"], key="exp_cat")
            sug = {
                "Needs": ["Renta","Alimentación","Transporte","Servicios"],
                "Wants":["Ocio","Compras","Restaurantes","Viajes"],
                "Savings":["Fondo emergencia","Inversión","Ahorro meta"],
                "Deuda":["Pago préstamo"], "Pago tarjeta":["Saldo tarjeta"]
            }
            used = sorted({t.subcat for t in b.expenses if t.category==gcat})
            sel = st.selectbox("Sub-cat", ["Otro…"] + sug.get(gcat,[]) + used, key="exp_sub_sel")
            gsub= st.text_input("Nueva sub-cat", key="exp_sub_new") if sel=="Otro…" else sel
            src = st.selectbox("Fuente", [a.name for a in b.accounts]+[c.name for c in b.cards], key="exp_src")
            grec= st.checkbox("Recurrente", key="exp_rec")
            if st.form_submit_button("Guardar gasto") and gsub:
                for a in b.accounts:
                    if a.name==src: a.balance -= gam
                for c in b.cards:
                    if c.name==src:
                        c.balance += gam
                        if c.cashback:
                            cb = gam * c.cashback / 100
                            c.balance -= cb
                            for a in b.accounts:
                                if a.type=="Débito": a.balance += cb; break
                b.expenses.append(Transaction(gdt.isoformat(), gam, gcat, gsub, src, grec))
                save_budget(user, prof, b); _rerun()

    # Cuerpo principal
    st.title(f"📊 Presupuesto — {prof}")

    # Recordatorios tarjetas
    for c in b.cards:
        pay_date = dt.date(TODAY.year, TODAY.month, c.pay_day)
        if 0 <= (pay_date - TODAY).days <= 5:
            st.warning(f"💳 {c.name}: paga antes del {pay_date.strftime('%d/%m')}")

    # Saldos
    st.subheader("Saldos actuales")
    bal_df = pd.DataFrame(
        [{"Fuente":a.name,"Tipo":a.type,"Saldo":a.balance} for a in b.accounts] +
        [{"Fuente":c.name,"Tipo":"Crédito","Saldo":-c.balance,"Límite":c.limit} for c in b.cards]
    )
    st.dataframe(bal_df.style.format({"Saldo":"RD$ {:,.0f}","Límite":"RD$ {:,.0f}"}))

    passive = sum(a.balance * a.rate / 100 / 12 for a in b.accounts)
    st.metric("Ingresos pasivos (mes)", f"RD$ {passive:,.0f}")

    # Distribución 50-20-30
    needs  = sum(t.amount for t in b.expenses if t.category=="Needs"   and _ym(t.date)==(y,m))
    wants  = sum(t.amount for t in b.expenses if t.category=="Wants"   and _ym(t.date)==(y,m))
    saves  = sum(t.amount for t in b.expenses if t.category=="Savings" and _ym(t.date)==(y,m))
    pie_df = pd.DataFrame({"Monto":[needs,wants,saves]}, index=["Needs","Wants","Savings"])
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Distribución 50-20-30 (mes)")
        st.pyplot(pie50(pie_df))
    with c2:
        cat_df = (
            pd.DataFrame([t.amount for t in b.expenses if _ym(t.date)==(y,m)],
                         index=[t.category for t in b.expenses if _ym(t.date)==(y,m)],
                         columns=["Monto"])
            .groupby(level=0).sum()
        )
        st.subheader("Gasto por categoría (mes)")
        if not cat_df.empty: st.pyplot(bar_spend(cat_df))
        else: st.info("Sin gastos este mes")

    # Evolución mensual
    evo = pd.DataFrame(b.expenses)
    if not evo.empty:
        evo["Mes"] = pd.to_datetime(evo["date"]).dt.to_period("M")
        evol = evo.pivot_table(index="Mes", columns="category", values="amount", aggfunc="sum").fillna(0)
        st.subheader("Evolución mensual de gastos")
        st.pyplot(line_month(evol))

    # Forecast 12 meses
    avg_cf = sum(b.cashflow_m(y, i) for i in range(1,13)) / 12
    months = pd.date_range(first_m(y,m), periods=12, freq="M")
    st.subheader("Forecast 12 meses (cash-flow medio)")
    st.line_chart(pd.DataFrame({"Cash-Flow":[avg_cf]*12}, index=months.strftime("%b %Y")))

    # Eliminación de Ingresos
    st.subheader("Ingresos")
    if b.incomes:
        inc_df = pd.DataFrame([asdict(t) for t in b.incomes])
        inc_df["Monto"] = inc_df["amount"]
        st.dataframe(
            inc_df[["date","category","subcat","source","Monto"]]
            .rename(columns={"date":"Fecha","category":"Cat","subcat":"Sub","source":"Fuente"})
        )
        to_del = st.multiselect(
            "Selecciona índices para eliminar ingresos",
            options=inc_df.index.tolist(),
            format_func=lambda i: f"{i}: RD$ {inc_df.loc[i,'Monto']:,.2f}"
        )
        if st.button("Eliminar ingresos seleccionados"):
            for idx in sorted(to_del, reverse=True):
                t = b.incomes.pop(idx)
                for a in b.accounts:
                    if a.name==t.source: a.balance -= t.amount
                for c in b.cards:
                    if c.name==t.source: c.balance += t.amount
            save_budget(user, prof, b); _rerun()
    else:
        st.info("Sin ingresos registrados")

    # Eliminación de Gastos
    st.subheader("Gastos")
    if b.expenses:
        exp_df = pd.DataFrame([asdict(t) for t in b.expenses])
        exp_df["Monto"] = exp_df["amount"]
        st.dataframe(
            exp_df[["date","category","subcat","source","Monto"]]
            .rename(columns={"date":"Fecha","category":"Cat","subcat":"Sub","source":"Fuente"})
        )
        to_del = st.multiselect(
            "Selecciona índices para eliminar gastos",
            options=exp_df.index.tolist(),
            format_func=lambda i: f"{i}: RD$ {exp_df.loc[i,'Monto']:,.2f}"
        )
        if st.button("Eliminar gastos seleccionados"):
            for idx in sorted(to_del, reverse=True):
                t = b.expenses.pop(idx)
                for a in b.accounts:
                    if a.name==t.source: a.balance += t.amount
                for c in b.cards:
                    if c.name==t.source: c.balance -= t.amount
            save_budget(user, prof, b); _rerun()
    else:
        st.info("Sin gastos registrados")

    # Historial global
    st.subheader("Historial global")
    if b.incomes or b.expenses:
        comb = (
            [{"Fecha":t.date,"Tipo":"Ingreso","Cat":t.category,"Sub":t.subcat,
              "Fuente":t.source,"Monto":t.amount} for t in b.incomes] +
            [{"Fecha":t.date,"Tipo":"Gasto","Cat":t.category,"Sub":t.subcat,
              "Fuente":t.source,"Monto":-t.amount} for t in b.expenses]
        )
        hdf = pd.DataFrame(comb).sort_values("Fecha",ascending=False).reset_index(drop=True)
        st.dataframe(hdf.style.format({"Monto":"RD$ {:,.0f}"}))
    else:
        st.info("Aún no hay movimientos")

def main():
    st.set_page_config("Presupuesto 50-20-30", layout="wide")
    if "user" not in st.session_state:
        login_screen(); return
    choose_profile(st.session_state.user)
    dashboard()

if __name__ == "__main__":
    main()
