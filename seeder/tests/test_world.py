import json
import re
import unicodedata
from ipaddress import ip_address, ip_network

from seeder import identifiers
from seeder.names import all_greek_people
from seeder.world import DATA_DIR, TEAM_SIZES, build_world, load_world

TEAMS = ["Sales", "Legal", "Finance", "Engineering", "HR", "Customer Support"]


def test_the_world_is_the_same_on_every_build_and_matches_the_committed_files() -> None:
    world = build_world()
    assert world == build_world()
    assert world == load_world()
    clients = json.loads((DATA_DIR / "clients.json").read_text(encoding="utf-8"))
    assert clients == [client.model_dump() for client in world.clients]


def test_a_different_seed_gives_a_different_world() -> None:
    assert build_world(1).clients != build_world(2).clients


def test_six_teams_with_their_own_address_ranges() -> None:
    world = build_world()
    assert [team.name for team in world.teams] == TEAMS
    assert len({team.cidr for team in world.teams}) == 6
    assert len(world.employees) == sum(TEAM_SIZES.values()) == 40
    ranges = {team.name: ip_network(team.cidr) for team in world.teams}
    for employee in world.employees:
        assert ip_address(employee.ip) in ranges[employee.team]
    assert len({employee.user_id for employee in world.employees}) == 40


def test_the_demo_employee_works_in_sales_and_demo_staff_are_not_duplicated() -> None:
    employees = {employee.user_id: employee for employee in build_world().employees}
    assert employees["e.papadaki"].display_name == "Eleni Papadaki"
    assert employees["e.papadaki"].team == "Sales"
    assert not {"n.georgiou", "k.dimitriou"} & set(employees)


def test_clients_are_forty_companies_and_twenty_individuals_in_both_languages() -> None:
    clients = build_world().clients
    assert [client.id for client in clients] == [f"C{n:03d}" for n in range(1, 61)]
    assert sum(client.kind == "company" for client in clients) == 40
    assert sum(client.kind == "individual" for client in clients) == 20
    assert {client.language for client in clients} == {"el", "en"}
    assert {client.team for client in clients} <= set(TEAMS)


def test_every_client_identifier_validates() -> None:
    for client in build_world().clients:
        assert identifiers.is_valid_afm(client.afm), client.id
        assert identifiers.is_valid_iban(client.iban), client.id
        assert 1 <= len(client.contacts) <= 3
        assert len(client.aliases) <= 2
        for email in [client.email, *(contact.email for contact in client.contacts)]:
            assert email.endswith(".example"), email
        for phone in [client.phone, *(contact.phone for contact in client.contacts)]:
            assert re.fullmatch(r"\+30 \d{3} \d{3} \d{4}", phone)
    afms = [client.afm for client in build_world().clients]
    assert len(set(afms)) == len(afms)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in plain if not unicodedata.combining(char)).replace("ς", "σ")


def test_abbreviations_are_unique_and_cannot_be_mistaken_for_a_name() -> None:
    companies = [client for client in build_world().clients if client.kind == "company"]
    abbreviations = [_fold(client.aliases[0]) for client in companies]
    assert len(set(abbreviations)) == len(abbreviations)
    name_words = {_fold(word) for person in all_greek_people() for word in person.name.split()}
    assert not set(abbreviations) & name_words


def test_the_scene_client_is_a_greek_company_owned_by_sales() -> None:
    client = build_world().scene_client
    assert (client.id, client.kind, client.team, client.language) == (
        "C001",
        "company",
        "Sales",
        "el",
    )
    assert client.contacts[0].name == "Μαρία Παπαδοπούλου"
    assert client.aliases[1] == "Astrolithi Pliroforiki"


def test_project_codes_match_the_custom_pattern() -> None:
    world = build_world()
    pattern = re.compile(world.project_pattern.regex)
    assert len(world.projects) == 6
    assert all(pattern.fullmatch(project.code) for project in world.projects)
    assert not pattern.search("PRJ-12-ABCD")
