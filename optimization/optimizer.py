# Utils
from pathlib import Path  
import numpy as np
import time
# utils from skopt and sklearn
from sklearn.gaussian_process.kernels import Matern
from skopt.learning import GaussianProcessRegressor,RandomForestRegressor,ExtraTreesRegressor
from skopt          import Optimizer as skopt_optimizer
from skopt.utils    import dimensions_aslist
#utils from other files of the framework
from models.model                import save_model_output
from optimization.optimizer_tool import save_csv,early_condition
from optimization.optimizer_tool import plot_bayesian_optimization,plot_model_runs
from optimization.optimizer_tool import BestEvaluation

class Optimizer:
    """
    Optimizer optimize hyperparameters to build topic models
    """

    # Values of hyperparameters and metrics for each iteration
    _iterations = []                    #counter for the BO iteration
    topk = 10                           # if False the topk words will not be computed
    topic_word_matrix = True            # if False the matrix will not be computed
    topic_document_matrix = True        # if False the matrix will not be computed

    def __init__(self, model, 
             dataset, 
             metric,
             search_space,
             extra_metrics=[],
             number_of_call=5, 
             n_random_starts=3,
             optimization_type='Maximize',
             model_runs=5,
             surrogate_model="RF",
             kernel=1.0 * Matern(length_scale=1.0, 
                                 length_scale_bounds=(1e-1, 10.0), nu=1.5),
             acq_func="LCB",
             random_state=False,
             x0=[],
             y0=[],
             save_csv=False,
             save_models=False,
             save_step=1,
             save_name="result",
             save_path="results/",
             early_stop=False,
             early_step=5,
             plot_best_seen=False,
             plot_model=False,
             plot_prefix_name="B0_plot",
             log_scale_plot=False):
        
        """
        blablabla
        """
        
        self.model = model                                                     #inizialize the model
        self.dataset = dataset                                                 #inizialize the dataset
        self.metric = metric                                                   #metric
        self.search_space = search_space                                       #inizialize the search space
        self.current_call = 0                                                  #iteration of Optimization process
        self.hyperparameters = list(sorted(self.search_space.keys()))
        self.extra_metrics = extra_metrics
        self.optimization_type = optimization_type
        self.matrix_model_runs = np.zeros((1+len(extra_metrics),number_of_call,model_runs))
        self.number_of_call=number_of_call
        self.n_random_starts=n_random_starts
        self.model_runs=model_runs
        self.surrogate_model=surrogate_model
        self.kernel=kernel
        self.acq_func=acq_func
        self.random_state=random_state
        self.x0=x0
        self.y0=y0
        self.save_csv=save_csv
        self.save_step=save_step
        self.save_name=save_name
        self.early_stop=early_stop
        self.early_step=early_step
        self.plot_model=plot_model,
        self.plot_best_seen=plot_best_seen
        self.plot_prefix_name=plot_prefix_name
        self.log_scale_plot=log_scale_plot
        self.save_models=save_models
        if (save_path[-1] != '/'):
            self.save_path = save_path + '/'
        else:
            self.save_path=save_path
            
        #create the directory where the results are saved
        if any((self.save_csv,self.save_models,self.plot_best_seen,self.plot_model)):
            Path(save_path).mkdir(parents=True, exist_ok=True)
        
        #create of the sub-directory where the models are saved
        if self.save_models == True:
            self.model_path_models = save_path + "models/"
            Path(self.model_path_models).mkdir(parents=True, exist_ok=True)

    def _objective_function(self, hyperparameters):
        """
        objective function to optimize

        Parameters
        ----------
        hyperparameters : dictionary of hyperparameters
                          (It's a list for real)
                          key: name of the parameter
                          value: skopt search space dimension

        Returns
        -------
        result : score of the metric to maximize
        """

        # Retrieve parameters labels
        params = {}
        for i in range(len(self.hyperparameters)):
            params[self.hyperparameters[i]] = hyperparameters[i]

        # Compute the score of the hyper-parameter configuration
        different_model_runs = []
        for i in range(self.model_runs):
            
            # Prepare model
            model_output = self.model.train_model(self.dataset, params, 
                                                  self.topk,
                                                  self.topic_word_matrix,
                                                  self.topic_document_matrix)
            #Score of the model 
            score = self.metric.score(model_output)            

            different_model_runs.append(score)

            self.matrix_model_runs[0,self.current_call, i] = score
            
            #Update of the extra metric values
            j=1
            for extra_metric in self.extra_metrics:
                self.matrix_model_runs[j,self.current_call, i]= extra_metric.score(model_output)
                j=j+1
            
            # Save the model for each run
            if self.save_models:
                name = str(self.current_call) + "_" + str(i) 
                save_model_path = self.model_path_models + name
                save_model_output(model_output, save_model_path)
                
        #the output for BO is the median over different_model_runs 
        result = np.median(different_model_runs)

        if self.optimization_type == 'Maximize':
            result = - result

        # Update evaluation of objective function
        self.current_call = self.current_call + 1

        #Boxplot for matrix_model_runs
        if self.plot_model:
            plot_model_runs(self.matrix_model_runs[0,:self.current_call,:], 
                        self.plot_prefix_name.split(".")[0]+"_model_runs_"+self.metric.__class__.__name__, 
                         self.save_path)
            #Boxplot of extrametrics (if any)
            j=1
            for extra_metric in self.extra_metrics:
                 plot_model_runs(self.matrix_model_runs[j,:self.current_call,:], 
                        self.plot_prefix_name.split(".")[0]+"_model_runs_"+self.metric.__class__.__name__, 
                         self.save_path)
                 j=j+1
                 
        return result

    def optimize(self):
        """
        Optimize the hyperparameters of the model

        Parameters
        ----------

        Returns
        -------
        result : Best_evaluation object
        """
        
        # Save parameters labels to use
        self.hyperparameters = list(sorted(self.search_space.keys()))
        params_space_list = dimensions_aslist(self.search_space)

        if self.number_of_call <= 0:
            print("Error: number_of_call can't be <= 0")
            return None
        
        if self.save and self.save_path is not None:
            Path(self.save_path).mkdir(parents=True, exist_ok=True)
        
        #### Choice of the surrogate model
        # Random forest
        if self.surrogate_model == "RF":
            estimator=RandomForestRegressor(n_estimators=100, min_samples_leaf=3)
            surrogate_model_name = "random_forest"
        # Extra Tree
        elif self.surrogate_model == "ET":
            estimator=ExtraTreesRegressor(n_estimators=100,min_samples_leaf=3)
            surrogate_model_name = "extra tree regressor"            
        # GP Minimize
        elif self.surrogate_model == "GP":
            estimator = GaussianProcessRegressor(kernel=self.kernel,random_state=self.random_state)
            surrogate_model_name = "gaussian process" 
        # Random Search
        elif self.surrogate_model == "RS":
            estimator="dummy"
            surrogate_model_name = "random_minimize" 
        else:
             print("Error: surrogate_model does not exist ")
             return None           
        #print of information about the optimization

        #Creation of a general skopt optimizer
        opt = skopt_optimizer(params_space_list, base_estimator=estimator, 
                              acq_func=self.acq_func,
                              n_initial_points=self.n_random_starts,
                              acq_optimizer="sampling", 
                              acq_optimizer_kwargs={"n_points": 10000, "n_restarts_optimizer": 5,"n_jobs": 1},
                              acq_func_kwargs={"xi": 0.01, "kappa": 1.96},
                              random_state=self.random_state)
              
        time_eval = []
        
        
        if len(self.x0)!=0:
            if len(self.y0)!=0:
                #Update of matrix_model_runs and current_call
                for i in range(len(self.y0)):    
                    self.matrix_model_runs[0,self.current_call,:]=self.y0[i]
                    self.current_call = self.current_call + 1
                
                #If the problem is a maximization problem, the values are multiplied by -1
                if self.optimization_type == 'Maximize':
                    self.y0 = [- self.y0[i] for i in range(len(self.y0))]  
                    
                #update of the model through x0,y0
                res=opt.tell(self.x0,self.y0,fit=True)
                
                #the computational time is 0 for x0,y0
                time_eval.extend([0]*len(self.y0)) 

            else:
                #The values of y0 must be computed
                for i in self.x0:
                    print("Current call: ", self.current_call+1)
                    start_time = time.time()
                    f_val = self._objective_function(i)                
                    res=opt.tell(i, f_val)      
                    end_time = time.time()
                    total_time = end_time - start_time
                    time_eval.append(total_time)                     
    
        #Update of number of calls 
        number_of_call_r=self.number_of_call-len(self.x0)

        if number_of_call_r <= 0:
              print("Error: number_of_call is less then len(x0)")
              return None

        ####for loop to perform Bayesian Optimization        
        for i in range(number_of_call_r):          
            print("Current call: ", self.current_call+1)
            start_time = time.time()  
            next_x = opt.ask()                              #next point proposed by BO
            f_val = self._objective_function(next_x)        #evaluation of the objective function for next_x
            res=opt.tell(next_x, f_val)                     #update of the opt using (next_x,f_val)
            
            end_time = time.time()
            total_time_function = end_time - start_time     #computational time for next_x (BO+Function evaluation)
            time_eval.append(total_time_function)
            
            #save the results on a csv file
            if self.save_csv:
                save_csv(name_csv=self.save_path+self.save_name,
                         res=res,
                         matrix_model_runs=self.matrix_model_runs[:,:self.current_call,:], 
                         extra_metrics=self.extra_metrics,
                         dataset_name=self.dataset.get_metadata()["info"]["name"],
                         hyperparameters_name=self.hyperparameters,
                         metric_name=self.metric.__class__.__name__,
                         surrogate_model_name=surrogate_model_name, 
                         acquisition_function_name=self.acq_func,
                         times=time_eval)    
            
            #Plot best seen 
            if self.plot_best_seen:  
                plot_bayesian_optimization(res, self.plot_prefix_name.split(".")[0]+"_best_seen", self.log_scale_plot,
                                                path=self.save_path,conv_max=self.optimization_type == 'Maximize')

            #Early stop condition
            if self.early_stop and  early_condition(res, self.early_step, self.n_random_starts):
                print("Stop because of early stopping condition")
                break  

            #Create an object related to the BO optimization
            Results= BestEvaluation(resultsBO=res,
                                  matrix_model_runs=self.matrix_model_runs,
                                  extra_metrics=self.extra_metrics,
                                  optimization_type=self.optimization_type) 
            
            if i % self.save_step == 0:
                Results.save(self.save_name)
            #name_csv.split(sep=".")[0]+".csv"
            
            return Results    