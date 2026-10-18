"""Small, explicitly synthetic household examples using the shared pipeline."""
from dataclasses import asdict
from datetime import date
from solar_saver.domain import CityScenario, ForecastRequest, Priority, SchedulerWeights, SimulationConfig, SolarProfile, Workload
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler

class HouseholdSolar:
    def predict(self, request):
        return SolarProfile((0,0,0,0,0,0,0,1,2,4,6,8,8,7,6,4,2,1,0,0,0,0,0,0), "Illustrative household solar")

class HouseholdDemand:
    def __init__(self, shift):
        self.shift = shift
    def generate(self, solar_profile, config):
        loads = tuple(Workload(name, "example-home", name, power, duration,
            max(8, 18-self.shift), min(24, 18+duration+self.shift), 18,
            Priority.FLEXIBLE, self.shift/10) for name,power,duration in
            (("EV charging",3.6,3),("Dishwasher",1.2,2),("Laundry",0.8,1)))
        return CityScenario(solar_profile.supply_kw, (0.5,)*24, (7.0,)*24, loads)

def household_examples():
    examples = {}
    for label, shift in (("fixed",0),("some",3),("open",10)):
        report = run_comparison(forecast_request=ForecastRequest(38.0293,-78.4767,date(2026,10,18),8),
            simulation_config=SimulationConfig(number_of_users=1), scheduler_weights=SchedulerWeights(),
            forecaster=HouseholdSolar(), demand_generator=HouseholdDemand(shift), scheduler=GreedyLoadScheduler())
        examples[label] = {strategy.value: {"metrics":asdict(item.metrics),
            "assignments":[asdict(a) for a in item.result.assignments]} for strategy,item in report.strategies.items()}
    return examples
